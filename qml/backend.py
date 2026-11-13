"""Snapshelf backend, called from QML through pyotherside.

* Snap Store API v2 (arm64 only) with a small in-memory cache
* snapd REST API on /run/snapd.socket (read-only calls work as a normal user)
* privileged actions (install/remove/refresh/connect) through ``sudo -S``: the password is
  checked once and kept only in memory while the app runs
* a single worker thread runs the queued actions one after another and reports progress
* Lomiri launcher (sidebar) pinning through GSettings
* optional "compatibility mode": start a snap in a nested X11 server with Mesa Turnip+Zink
  (for snaps whose Vulkan/Wayland output never reaches Mir 1.8 through libhybris)
"""
import ast
import gettext
import glob
import http.client
import json
import os
import queue
import re
import shlex
import socket
import subprocess
import threading
import time
import urllib.parse
import urllib.request

try:
    import pyotherside
except ImportError:  # unit tests / running outside the app
    class _NoPyotherside:
        @staticmethod
        def send(*args):
            pass
    pyotherside = _NoPyotherside()

try:
    import yaml
except ImportError:  # pragma: no cover - python3-yaml is part of Ubuntu Touch
    yaml = None

APP_ID = "snapshelf.giovix64"
APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ = gettext.translation(APP_ID, os.path.join(APP_DIR, "share", "locale"), fallback=True).gettext

STORE = "https://api.snapcraft.io/v2/snaps"
ARCH = "arm64"
HEADERS = {"Snap-Device-Series": "16", "Snap-Device-Architecture": ARCH,
           "User-Agent": "snapshelf/0.3.1 (Ubuntu Touch)"}
FIND_FIELDS = "title,summary,base,confinement,version,media,publisher,type"
INFO_FIELDS = ("title,summary,description,base,confinement,version,media,publisher,license,"
               "website,contact,snap-yaml,download,created-at")
OLD_BASES = ("core22", "core20", "core18", "core")
GPU_PLUG = "gpu-2404"
GPU_PROVIDER = "hybris-2404"
GPU_SLOT = GPU_PROVIDER + ":gpu-2404"
CACHE_TTL = 300

HOME = os.path.expanduser("~")
SETTINGS_FILE = os.path.join(HOME, ".config", APP_ID, "settings.json")
DEFAULT_SETTINGS = {
    "pin_after_install": True,   # add new apps to the Lomiri launcher
    "connect_gpu": True,         # connect gpu-2404 to hybris-2404 when the snap supports it
    "devmode": True,             # the 4.14 kernel lacks the BPF device cgroup strict snaps need
    "hide_unsupported": False,   # hide classic snaps from the results
    "known_fixes": True,         # apply the launch mode known snaps need (telegram-desktop…)
}
SNAP_DESKTOP_DIR = "/var/lib/snapd/desktop/applications"
USER_APPS_DIR = os.path.join(HOME, ".local", "share", "applications")
LAUNCHER_SCHEMA = "com.lomiri.Shell.Launcher"
REEXEC_CONF = os.path.join(HOME, ".config", "environment.d", "90-snap-noreexec.conf")
COMPAT_PREFIX = "snapshelf-x11-"
MARK_COMPAT = "X-Snapshelf=compat"
XLAND_CANDIDATES = [os.path.join(HOME, ".local", "bin", "nabu-xland")]
MESA_CANDIDATES = [os.path.join(HOME, ".local", "share", "nabu-mesa"),
                   os.path.join(HOME, ".local", "share", "firefox.fuseteam", "nabu-mesa")]


# ===================================================================== small helpers
class _Cache:
    def __init__(self, ttl):
        self.ttl = ttl
        self._d = {}
        self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            v = self._d.get(key)
        if v and time.monotonic() - v[0] < self.ttl:
            return v[1]
        return None

    def put(self, key, value):
        with self._lock:
            self._d[key] = (time.monotonic(), value)
        return value

    def clear(self):
        with self._lock:
            self._d.clear()


_store_cache = _Cache(CACHE_TTL)


def _media(media, kind):
    return [m.get("url", "") for m in (media or []) if m.get("type") == kind]


def _channel_label(ch):
    track, risk = ch.get("track", "latest"), ch.get("risk", ch.get("name", "stable"))
    return risk if track == "latest" else "%s/%s" % (track, risk)


def human_size(n):
    try:
        n = float(n)
    except (TypeError, ValueError):
        return ""
    for unit in ("B", "kB", "MB", "GB"):
        if n < 1000 or unit == "GB":
            return ("%.0f %s" if unit in ("B", "kB") else "%.1f %s") % (n, unit)
        n /= 1000.0
    return ""


# ===================================================================== settings
def get_settings():
    s = dict(DEFAULT_SETTINGS)
    try:
        with open(SETTINGS_FILE) as f:
            s.update({k: v for k, v in json.load(f).items() if k in DEFAULT_SETTINGS})
    except (OSError, ValueError):
        pass
    return s


def set_setting(key, value):
    s = get_settings()
    if key in DEFAULT_SETTINGS:
        s[key] = bool(value)
        os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
        with open(SETTINGS_FILE, "w") as f:
            json.dump(s, f, indent=1)
    return s


# ===================================================================== snapd
class _UnixHTTP(http.client.HTTPConnection):
    def __init__(self, path, timeout=30):
        super().__init__("localhost", timeout=timeout)
        self._path = path

    def connect(self):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(self.timeout)
        s.connect(self._path)
        self.sock = s


def snapd_get(path):
    """GET on the snapd REST API; returns the ``result`` member (None on error)."""
    c = _UnixHTTP("/run/snapd.socket")
    try:
        c.request("GET", path)
        return json.loads(c.getresponse().read()).get("result")
    except (OSError, ValueError, http.client.HTTPException):
        return None
    finally:
        c.close()


def _installed_raw():
    return snapd_get("/v2/snaps") or []


def _installed_map():
    return {s.get("name"): s for s in _installed_raw()}


# ===================================================================== compatibility rules
def compat(base, confinement, gpu=None):
    """Return (level, text) for a snap on this device.

    level: ``gpu`` (hardware accelerated through hybris-2404), ``good`` (core24, GPU possible),
    ``ok`` (works with software rendering) or ``no`` (not supported).
    ``gpu`` is None when the snap.yaml is not known yet (search results).
    """
    if confinement == "classic":
        return "no", _("Classic confinement: not supported on Ubuntu Touch")
    if gpu:
        return "gpu", _("Works, GPU accelerated (hybris-2404)")
    if base == "core24":
        if gpu is None:
            return "good", _("core24: GPU acceleration possible")
        return "ok", _("core24: works, software rendering")
    if base in OLD_BASES:
        return "ok", _("%s: works, software rendering") % base
    return "ok", _("Should work")


def notes_for(snap_yaml, gpu, devmode):
    """Human readable hints taken from the snap.yaml plugs."""
    notes = []
    plugs = _yaml_plugs(snap_yaml)
    if "wayland" in plugs and "x11" not in plugs:
        notes.append(_("Wayland only: the window may stay empty on Mir 1.8 (try the compatibility mode)"))
    if not gpu and ("opengl" in plugs or "gpu-2404" in plugs):
        notes.append(_("Uses OpenGL without hybris: 3D will be slow (software)"))
    if devmode:
        notes.append(_("Installed in devmode (needed by the 4.14 kernel)"))
    return notes


def _yaml_plugs(snap_yaml):
    """Set of plug names/interfaces used by the snap (top level and apps)."""
    if not snap_yaml:
        return set()
    if yaml is None:
        return set(re.findall(r"[A-Za-z0-9][\w-]*", snap_yaml))  # rough, but good enough for plug names
    try:
        y = yaml.safe_load(snap_yaml) or {}
    except yaml.YAMLError:
        return set()
    out = set()
    for name, val in (y.get("plugs") or {}).items():
        out.add(name)
        if isinstance(val, dict) and val.get("interface"):
            out.add(val["interface"])
    for app in (y.get("apps") or {}).values():
        out.update((app or {}).get("plugs") or [])
    return out


# ===================================================================== store
def _store_get(url):
    hit = _store_cache.get(url)
    if hit is not None:
        return hit
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=25) as r:
        return _store_cache.put(url, json.loads(r.read()))


def _item(x, installed, updates):
    s = x.get("snap", {}) or {}
    r = x.get("revision", {}) or {}
    pub = s.get("publisher") or {}
    name = x.get("name", "")
    level, text = compat(r.get("base"), r.get("confinement"))
    icons = _media(s.get("media"), "icon")
    return {
        "name": name,
        "title": s.get("title") or name,
        "summary": s.get("summary", ""),
        "icon": icons[0] if icons else "",
        "publisher": pub.get("display-name", ""),
        "verified": pub.get("validation") in ("verified", "starred"),
        "version": r.get("version", ""),
        "level": level,
        "compat": text,
        "type": r.get("type") or s.get("type") or "app",
        "installed": name in installed,
        "update": name in updates,
    }


def categories():
    try:
        cats = _store_get(STORE + "/categories").get("categories", [])
    except Exception:
        return []
    names = [c["name"] for c in cats if c.get("name") and c["name"] != "featured"]
    return [{"name": n, "title": n.replace("-", " ").capitalize()} for n in names]


def search(query, category=""):
    query = (query or "").strip()
    params = {"fields": FIND_FIELDS, "architecture": ARCH}  # without architecture: amd64-only snaps too
    if query:
        params["q"] = query
    if category or not query:
        params["category"] = category or "featured"
    try:
        res = _store_get(STORE + "/find?" + urllib.parse.urlencode(params)).get("results", [])
    except Exception as e:
        return {"error": _("Snap Store not reachable: %s") % e, "items": []}
    installed = _installed_map()
    updates = {u.get("name") for u in (snapd_get("/v2/find?select=refresh") or [])}
    items = [_item(x, installed, updates) for x in res]
    items = [i for i in items if i["type"] == "app"]
    if get_settings()["hide_unsupported"]:
        items = [i for i in items if i["level"] != "no"]
    if not query:
        order = {"gpu": 0, "good": 1, "ok": 2, "no": 3}
        items.sort(key=lambda i: order.get(i["level"], 2))
    return {"error": "", "items": items}


def info(name):
    params = {"fields": INFO_FIELDS, "architecture": ARCH}
    try:
        d = _store_get(STORE + "/info/" + urllib.parse.quote(name) + "?" + urllib.parse.urlencode(params))
    except Exception as e:
        d = None
        err = _("Snap Store not reachable: %s") % e
    inst = _installed_map().get(name)
    if d is None and inst is None:
        return {"error": err}
    s = (d or {}).get("snap", {}) or {}
    cm = [c for c in (d or {}).get("channel-map", []) if c.get("channel", {}).get("architecture") == ARCH]
    order = {"stable": 0, "candidate": 1, "beta": 2, "edge": 3}
    cm.sort(key=lambda c: (c["channel"].get("track") != "latest", order.get(c["channel"].get("risk"), 9)))
    channels = [{
        "name": c["channel"].get("track", "latest") + "/" + c["channel"].get("risk", ""),
        "label": _channel_label(c["channel"]),
        "version": c.get("version", ""),
        "size": human_size((c.get("download") or {}).get("size")),
        "released": (c["channel"].get("released-at") or "")[:10],
    } for c in cm]
    chan = cm[0] if cm else {}
    snap_yaml = chan.get("snap-yaml") or ""
    gpu = GPU_PLUG in _yaml_plugs(snap_yaml)
    base = chan.get("base") or (inst or {}).get("base", "") or ""
    level, text = compat(base, chan.get("confinement") or (inst or {}).get("confinement"),
                         gpu if base == "core24" else None)
    if d is not None and not cm:
        level, text = "no", _("No arm64 version of this snap")
    pub = s.get("publisher") or (inst or {}).get("publisher") or {}
    icons = _media(s.get("media") or (inst or {}).get("media"), "icon")
    apps = _snap_apps(name) if inst else []
    devmode = get_settings()["devmode"]
    return {
        "error": "",
        "name": name,
        "title": s.get("title") or (inst or {}).get("title") or name,
        "summary": s.get("summary") or (inst or {}).get("summary", ""),
        "description": s.get("description") or (inst or {}).get("description", ""),
        "publisher": pub.get("display-name", ""),
        "verified": pub.get("validation") in ("verified", "starred"),
        "license": s.get("license") or (inst or {}).get("license", "") or "",
        "website": s.get("website") or "",
        "icon": icons[0] if icons else "",
        "screenshots": _media(s.get("media"), "screenshot")[:8],
        "channels": channels,
        "version": chan.get("version", ""),
        "size": human_size((chan.get("download") or {}).get("size")),
        "base": base,
        "confinement": chan.get("confinement") or (inst or {}).get("confinement", ""),
        "gpu": gpu,
        "level": level,
        "compat": text,
        "notes": notes_for(snap_yaml, gpu, devmode and not inst),
        "installed": inst is not None,
        "installed_version": (inst or {}).get("version", ""),
        "installed_channel": (inst or {}).get("tracking-channel") or (inst or {}).get("channel", ""),
        "installed_devmode": bool((inst or {}).get("devmode")),
        "gpu_connected": _gpu_connected(name) if inst else False,
        "update": bool(inst) and any(u.get("name") == name for u in (snapd_get("/v2/find?select=refresh") or [])),
        "has_apps": bool(apps),
        "pinned": is_pinned(name),
        "compat_mode": compat_mode_enabled(name),
        "launch_mode": launch_mode(name) if inst else "default",
        "known_fix": KNOWN_FIXES.get(name, ""),
        "running": bool(running_pids(name)) if inst else False,
        "queued": name in _queued_names(),
    }


# ===================================================================== installed / updates
def installed():
    snaps = _installed_raw()
    updates = {u.get("name"): u.get("version", "") for u in (snapd_get("/v2/find?select=refresh") or [])}
    out = []
    for s in snaps:
        if s.get("type") != "app" or not s.get("apps"):
            continue  # skip bases, snapd and content-only snaps (gnome-46-2404, hybris-2404…)
        name = s.get("name", "")
        icons = _media(s.get("media"), "icon")
        apps = _snap_apps(name)
        icon = icons[0] if icons else (apps[0]["icon"] if apps else "")
        sub = s.get("version", "")
        if name in updates:
            sub += "  →  " + updates[name]
        out.append({
            "name": name,
            "title": s.get("title") or name,
            "summary": s.get("summary", ""),
            "icon": icon,
            "publisher": (s.get("publisher") or {}).get("display-name", ""),
            "verified": False,
            "version": sub,
            "level": "update" if name in updates else ("devmode" if s.get("devmode") else "ok"),
            "compat": "",
            "installed": True,
            "update": name in updates,
            "installed_size": human_size(s.get("installed-size")),
        })
    out.sort(key=lambda i: (not i["update"], i["title"].lower()))
    return out


def updates_count():
    return len(snapd_get("/v2/find?select=refresh") or [])


def _gpu_connected(name):
    res = snapd_get("/v2/connections?snap=" + urllib.parse.quote(name)) or {}
    for c in res.get("established", []) or []:
        if c.get("plug", {}).get("plug") == GPU_PLUG and c.get("slot", {}).get("snap") == GPU_PROVIDER:
            return True
    return False


# ===================================================================== apps of a snap (desktop files)
def _read_desktop(path):
    d = {}
    try:
        with open(path) as f:
            in_main = False
            for line in f:
                line = line.rstrip("\n")
                if line.startswith("["):
                    in_main = line == "[Desktop Entry]"
                elif in_main and "=" in line:
                    k, v = line.split("=", 1)
                    d.setdefault(k, v)
    except OSError:
        pass
    return d


def _snap_apps(name):
    """Graphical apps of an installed snap: [{id, name, icon, app}]."""
    out = []
    for f in sorted(glob.glob(os.path.join(SNAP_DESKTOP_DIR, glob.escape(name) + "_*.desktop"))):
        did = os.path.basename(f)[:-len(".desktop")]
        d = _read_desktop(f)
        if d.get("NoDisplay", "").lower() == "true":
            continue
        icon = re.sub(r"^/snap/([^/]+)/[^/]+/", r"/snap/\1/current/", d.get("Icon", ""))  # survive refreshes
        out.append({"id": did, "name": d.get("Name", name), "icon": icon,
                    "app": did[len(name) + 1:], "path": f})
    return out


def open_app(name):
    """Desktop id to open with Qt.openUrlExternally('application:///<id>.desktop')."""
    apps = _snap_apps(name)
    if not apps:
        return ""
    return _mode_id(launch_mode(name), apps[0]["id"])


# ===================================================================== Lomiri launcher (sidebar)
def _launcher_items():
    out = subprocess.run(["gsettings", "get", LAUNCHER_SCHEMA, "items"],
                         capture_output=True, text=True).stdout.strip()
    if out.startswith("@as "):
        out = out[4:]
    try:
        return list(ast.literal_eval(out))
    except (ValueError, SyntaxError):
        return []


def _set_launcher_items(items):
    subprocess.run(["gsettings", "set", LAUNCHER_SCHEMA, "items", str(list(items))], check=False)


def _mode_id(mode, desktop_id):
    """Desktop id of an app in a launch mode: snapshelf-x11-<snap>.<app>

    Lomiri reads ids with "_" as click/snap ids ("AppID is empty"), and lomiri-app-launch uses "--"
    as separator in its unit names, so with "--" Lomiri rejects the window ("desktop_file_hint could
    not be found"). Snap names cannot contain ".", so the dot is unambiguous."""
    if mode == "default":
        return desktop_id
    return MODES[mode]["prefix"] + desktop_id.replace("_", ".", 1)


def _all_prefixes(name):
    return tuple("appid://" + (name + "_" if m == "default" else MODES[m]["prefix"] + name + ".")
                 for m in MODES)


def is_pinned(name):
    return any(i.startswith(_all_prefixes(name)) for i in _launcher_items())


def pin(name, on):
    """Add (on=True) or remove the snap's apps from the Lomiri launcher. Returns the new state.

    The pinned icon is the one of the current launch mode ("App (GPU)" in X11 + GPU mode…)."""
    items = [i for i in _launcher_items() if not i.startswith(_all_prefixes(name))]
    if on:
        mode = launch_mode(name)
        items += ["appid://" + _mode_id(mode, a["id"]) for a in _snap_apps(name)]
    _set_launcher_items(items)
    return is_pinned(name)


# ===================================================================== launch modes (fixes for apps that do not show up)
# default : the snap's own launcher
# x11-gpu : nested landscape X server + Mesa Turnip/Zink instead of libhybris ("App (GPU)").
#           Fixes empty/grey windows and EGL errors of Qt6, wgpu/Vulkan, GTK4 apps on Mir 1.8.
# x11-sw  : nested X server, software rendering ("App (X11)")
# wl-safe : stays on Wayland, toolkits forced to software rendering ("App (safe)")
MODES = {
    "default": {"prefix": "", "suffix": "", "xland": False, "mesa": False},
    "x11-gpu": {"prefix": "snapshelf-x11-", "suffix": " (GPU)", "xland": True, "mesa": True},
    "x11-sw": {"prefix": "snapshelf-x11sw-", "suffix": " (X11)", "xland": True, "mesa": False},
    "wl-safe": {"prefix": "snapshelf-safe-", "suffix": " (safe)", "xland": False, "mesa": False},
}
# snaps known to need a launch mode on Ubuntu Touch 24.04 (Mir 1.8 + libhybris)
KNOWN_FIXES = {
    "telegram-desktop": "x11-gpu",   # Qt6: "Cannot find EGLConfig", eglSwapBuffers fails on hybris
    "pdfcraft": "x11-gpu",           # wgpu/Vulkan: window stays grey
}


def _find_first(paths, test):
    for p in paths:
        if test(p):
            return p
    return ""


def _helpers():
    xland = _find_first(XLAND_CANDIDATES, lambda p: os.access(p, os.X_OK))
    mesa = _find_first(MESA_CANDIDATES, lambda p: os.path.exists(os.path.join(p, "freedreno_icd.json")))
    return xland, mesa


def mode_support():
    """Which launch modes can be used on this device: {mode: {"available", "reason"}}."""
    xland, mesa = _helpers()
    out = {}
    for mode, m in MODES.items():
        reason = ""
        if m["xland"] and not xland:
            reason = _("Needs the nested X server helper (nabu-xland)")
        elif m["mesa"] and not mesa:
            reason = _("Needs Mesa Turnip built for KGSL")
        out[mode] = {"available": not reason, "reason": reason}
    return out


def compat_support():
    """Kept for the system checks: is the X11 + Turnip mode available?"""
    xland, mesa = _helpers()
    r = mode_support()["x11-gpu"]
    return dict(r, xland=xland, mesa=mesa)


def _runner_path():
    base = os.path.join("/opt/click.ubuntu.com", APP_ID, "current")
    root = base if os.path.isdir(base) else APP_DIR
    return os.path.join(root, "bin", "snapshelf-run")


def _app_command(name, app):
    """Command of a snap app relative to $SNAP, from meta/snap.yaml."""
    try:
        with open("/snap/%s/current/meta/snap.yaml" % name) as f:
            y = yaml.safe_load(f) if yaml else {}
        return ((y.get("apps") or {}).get(app) or {}).get("command", "") or ""
    except Exception:  # missing snap, bad yaml
        return ""


def _mode_files(name, mode):
    return glob.glob(os.path.join(USER_APPS_DIR, glob.escape(MODES[mode]["prefix"] + name) + ".*.desktop"))


def launch_mode(name):
    for mode in ("x11-gpu", "x11-sw", "wl-safe"):
        if _mode_files(name, mode):
            return mode
    return "default"


def compat_mode_enabled(name):
    return launch_mode(name) == "x11-gpu"


def set_launch_mode(name, mode):
    """Create the launchers of a launch mode ("<App> (GPU)"…), removing those of the other modes.

    The original launchers stay: Lomiri lists snap apps straight from snapd, so they cannot be hidden.
    """
    if mode not in MODES:
        return {"ok": False, "msg": "unknown mode", "mode": launch_mode(name)}
    sup = mode_support()[mode]
    if not sup["available"]:
        return {"ok": False, "msg": sup["reason"], "mode": launch_mode(name)}
    was_pinned = is_pinned(name)
    for m in MODES:
        if m != "default":
            for f in _mode_files(name, m):
                os.remove(f)
    if mode != "default":
        xland, _mesa = _helpers()
        os.makedirs(USER_APPS_DIR, exist_ok=True)
        for a in _snap_apps(name):
            cmd = _app_command(name, a["app"])
            if not cmd:
                continue
            snap_app = name if a["app"] == name else name + "." + a["app"]
            argv = ([xland, "--host"] if MODES[mode]["xland"] else []) + \
                [_runner_path(), mode, snap_app] + shlex.split(cmd)
            with open(os.path.join(USER_APPS_DIR, _mode_id(mode, a["id"]) + ".desktop"), "w") as f:
                f.write("[Desktop Entry]\nType=Application\nName=%s\nExec=%s\nIcon=%s\nTerminal=false\n"
                        "X-Lomiri-Supported-Orientations=%s\n%s\n"
                        % (a["name"] + MODES[mode]["suffix"], " ".join(shlex.quote(x) for x in argv), a["icon"],
                           "landscape;" if MODES[mode]["xland"] else "landscape;portrait;", MARK_COMPAT))
    if was_pinned:
        pin(name, True)
    now = launch_mode(name)
    return {"ok": now == mode, "msg": "", "mode": now}


def set_compat_mode(name, on):
    r = set_launch_mode(name, "x11-gpu" if on else "default")
    return {"ok": r["ok"], "msg": r["msg"], "enabled": r["mode"] == "x11-gpu"}


def _migrate_launchers():
    """Older versions wrote snapshelf-x11-<snap>_<app> (0.2.0) or <snap>--<app> (0.3.0) launchers,
    which Lomiri cannot start: rename them to <snap>.<app>."""
    def fix(base):
        return base.replace("_", ".", 1) if "_" in base else base.replace("--", ".", 1)
    for f in glob.glob(os.path.join(USER_APPS_DIR, "snapshelf-*.desktop")):
        base = os.path.basename(f)
        if base.startswith(APP_ID) or ("_" not in base and "--" not in base):
            continue
        try:
            os.rename(f, os.path.join(USER_APPS_DIR, fix(base)))
        except OSError:
            pass
    items = _launcher_items()
    fixed = [fix(i) if i.startswith("appid://snapshelf-") else i for i in items]
    if fixed != items:
        _set_launcher_items(fixed)


def apply_known_fix(name):
    """Apply the launch mode a snap is known to need (if the device supports it). Returns the mode or ''."""
    mode = KNOWN_FIXES.get(name, "")
    if mode and mode_support()[mode]["available"] and launch_mode(name) == "default":
        if set_launch_mode(name, mode)["ok"]:
            return mode
    return ""


# ===================================================================== diagnosis
# (pattern in the app log, suggested fix id, explanation)
DIAG_RULES = [
    ("GPU wrapper", "reset", _("The GPU content is connected but the snap environment is older: reset it")),
    ("not found: ensure slot is connected", "reset", _("The GPU content is connected but the snap environment is older: reset it")),
    ('library "libEGL.so" not found', "reexec", _("The snap cannot see the Android drivers (/android): use the Ubuntu Touch snapd tools and reset the environment")),
    ('library "libvulkan.so" not found', "reexec", _("The snap cannot see the Android drivers (/android): use the Ubuntu Touch snapd tools and reset the environment")),
    ("Cannot find EGLConfig", "x11-gpu", _("The app's EGL setup does not work with libhybris on Wayland: start it in X11 with the Turnip GPU driver")),
    ("eglSwapBuffers failed", "x11-gpu", _("The app's EGL setup does not work with libhybris on Wayland: start it in X11 with the Turnip GPU driver")),
    ("Context is lost", "x11-gpu", _("The app's EGL setup does not work with libhybris on Wayland: start it in X11 with the Turnip GPU driver")),
    ("device is lost", "x11-gpu", _("The GPU device was lost: start the app in X11 with the Turnip GPU driver")),
    ("glutin error", "x11-gpu", _("The app's EGL setup does not work with libhybris on Wayland: start it in X11 with the Turnip GPU driver")),
    ("Failed to create EGLConfig", "x11-gpu", _("The app's EGL setup does not work with libhybris on Wayland: start it in X11 with the Turnip GPU driver")),
    ("Failed to create wl_display", "x11-sw", _("The app cannot connect to Wayland: start it in X11")),
    ("cannot open display", "x11-sw", _("The app needs an X server: start it in X11")),
    ("Segmentation fault", "x11-gpu", _("The app crashed: if it uses the GPU, try it in X11 with the Turnip GPU driver")),
    ("apparmor=\"DENIED\"", "devmode", _("AppArmor blocks the app: switch it to devmode")),
    ("Permission denied", "devmode", _("Permission denied: switch the app to devmode")),
]


def _app_names(name):
    try:
        with open("/snap/%s/current/meta/snap.yaml" % name) as f:
            y = yaml.safe_load(f) if yaml else {}
        return list((y.get("apps") or {}).keys())
    except Exception:
        return [name]


def app_log(name, minutes=60, limit=80):
    """Recent journal lines of the snap's apps (and of the nested X server log in X11 modes)."""
    ids = set(_app_names(name)) | {name}
    args = ["journalctl", "--user", "--no-pager", "-o", "short-iso", "--since", "-%dmin" % minutes]
    for i in ids:
        args += ["-t", i]
    try:
        lines = subprocess.run(args, capture_output=True, text=True, timeout=20).stdout.splitlines()
    except (OSError, subprocess.SubprocessError):
        lines = []
    lines = [l for l in lines if not l.startswith("-- ")]
    if launch_mode(name) in ("x11-gpu", "x11-sw"):
        xlog = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/run/user/%d" % os.getuid()), "nabu-xland.log")
        try:
            with open(xlog, errors="replace") as f:
                xl = f.read().splitlines()[-200:]
            lines += [l for l in xl if "Could not resolve keysym" not in l and l.strip() != ">"]
        except OSError:
            pass
    return lines[-limit:]


def diagnose(name):
    """Read the app log, match known problems and suggest fixes."""
    lines = app_log(name)
    text = "\n".join(lines)
    seen, sugg = set(), []
    for pattern, fix, why in DIAG_RULES:
        if pattern in text and fix not in seen:
            seen.add(fix)
            sugg.append({"fix": fix, "text": why, "pattern": pattern})
    mode = launch_mode(name)
    sugg = [s for s in sugg if s["fix"] != mode]            # already applied
    if not lines:
        sugg.append({"fix": "", "text": _("No log lines in the last hour: open the app once, then run the diagnosis again"), "pattern": ""})
    elif not sugg:
        sugg.append({"fix": "", "text": _("No known problem found in the log"), "pattern": ""})
    return {"lines": lines, "suggestions": sugg, "mode": mode}


def running_pids(name):
    """PIDs of the snap's running processes (from their cgroup)."""
    pids = []
    tag = "snap." + name + "."
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        try:
            with open("/proc/%s/cgroup" % d) as f:
                if tag in f.read():
                    pids.append(int(d))
        except OSError:
            pass
    return pids


def stop_app(name):
    """Terminate the snap's running processes (they belong to the user: no password needed)."""
    pids = running_pids(name)
    for pid in pids:
        try:
            os.kill(pid, 15)
        except OSError:
            pass
    return len(pids)


# ===================================================================== system checks
def system_status():
    inst = _installed_map()
    info_ = snapd_get("/v2/system-info") or {}
    reexec_ok = os.environ.get("SNAP_REEXEC") == "0" or os.path.exists(REEXEC_CONF)
    sup = compat_support()
    return {
        "snapd": info_.get("version", "?"),
        "snapd_snap": "snapd" in inst,
        "hybris": GPU_PROVIDER in inst,
        "reexec_ok": reexec_ok,
        "compat": sup["available"],
        "compat_reason": sup["reason"],
    }


def fix_reexec():
    """Keep `snap` on the distribution's snapd tools: only the UBports snap-confine mounts /android,
    which libhybris needs inside snaps (otherwise GPU snaps fail with 'libEGL.so not found')."""
    os.makedirs(os.path.dirname(REEXEC_CONF), exist_ok=True)
    with open(REEXEC_CONF, "w") as f:
        f.write("# Snapshelf: use the UBports snapd tools (snap-confine mounts /android for libhybris)\n"
                "SNAP_REEXEC=0\n")
    subprocess.run(["systemctl", "--user", "set-environment", "SNAP_REEXEC=0"], check=False)
    os.environ["SNAP_REEXEC"] = "0"
    return True


# ===================================================================== password and privileged actions
_password = None


def has_password():
    return _password is not None


def set_password(pw):
    """Check the password with sudo; keep it in memory only if it works."""
    global _password
    try:
        p = subprocess.run(["sudo", "-S", "-k", "-p", "", "-v"], input=pw + "\n",
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False
    if p.returncode == 0:
        _password = pw
        return True
    return False


def forget_password():
    global _password
    _password = None
    return True


def _sudo(args, timeout=3600):
    p = subprocess.run(["sudo", "-S", "-p", ""] + args, input=(_password or "") + "\n",
                       capture_output=True, text=True, timeout=timeout)
    return p.returncode, (p.stderr.strip() or p.stdout.strip())


def _wait_change(name, change_id, label):
    """Follow a snapd change, reporting progress (0..1, -1 = unknown)."""
    while True:
        ch = snapd_get("/v2/changes/" + change_id)
        if not ch:
            return None, ""
        done = total = 0
        for t in ch.get("tasks", []) or []:
            pr = t.get("progress", {}) or {}
            done += pr.get("done", 0)
            total += pr.get("total", 0)
            if t.get("status") == "Doing" and t.get("summary"):
                label = t["summary"]
        pyotherside.send("progress", name, (done / total) if total else -1, label)
        if ch.get("ready"):
            return ch.get("status") == "Done", ch.get("err", "")
        time.sleep(0.6)


def _run_change(name, args, label):
    pyotherside.send("progress", name, -1, label)
    rc, out = _sudo(["snap"] + args + ["--no-wait"])
    if rc != 0:
        return False, out
    change_id = out.strip().splitlines()[-1].strip() if out.strip() else ""
    if not change_id.isdigit():
        return True, ""
    ok, err = _wait_change(name, change_id, label)
    if ok is None:  # change not readable: assume finished
        return True, ""
    return ok, err


def _connect_gpu(name):
    if GPU_PROVIDER not in _installed_map():
        ok, err = _run_change(name, ["install", GPU_PROVIDER], _("Installing GPU support (hybris-2404)…"))
        if not ok:
            return False, err
    pyotherside.send("progress", name, -1, _("Connecting the GPU…"))
    rc, out = _sudo(["snap", "connect", name + ":" + GPU_PLUG, GPU_SLOT])
    # the mount namespace may already exist (install hooks) without the GPU content mount:
    # drop it so the next start rebuilds it with the GPU and /android
    _sudo(["/usr/lib/snapd/snap-discard-ns", name], timeout=60)
    return rc == 0, out


def _job_install(name, channel, gpu):
    st = get_settings()
    args = ["install", name] + (["--channel=" + channel] if channel else []) + (["--devmode"] if st["devmode"] else [])
    ok, err = _run_change(name, args, _("Installing %s…") % name)
    if not ok:
        return False, err or _("Installation failed")
    msg = _("Installed. You will find it in the app drawer.")
    if gpu and st["connect_gpu"]:
        gok, gerr = _connect_gpu(name)
        msg = _("Installed with GPU acceleration. You will find it in the app drawer.") if gok \
            else _("Installed, but the GPU could not be connected: %s") % gerr
    if st["known_fixes"]:
        mode = apply_known_fix(name)
        if mode == "x11-gpu":
            msg += " " + _("Known fix applied: use the \"(GPU)\" icon.")
        elif mode:
            msg += " " + _("Known fix applied.")
    if st["pin_after_install"] and _snap_apps(name):
        pin(name, True)
        msg += " " + _("Added to the launcher.")
    return True, msg


def _job_remove(name):
    had_mode = launch_mode(name) != "default"
    ok, err = _run_change(name, ["remove", name], _("Removing %s…") % name)
    if ok:  # launchers are found by prefix, so this works once the snap is gone
        pin(name, False)
        if had_mode:
            set_launch_mode(name, "default")
        return True, _("Removed.")
    return False, err or _("Removal failed")


def _job_refresh(name):
    ok, err = _run_change(name, ["refresh", name], _("Updating %s…") % name)
    return (True, _("Updated.")) if ok else (False, err or _("Update failed"))


def _job_switch(name, channel):
    ok, err = _run_change(name, ["refresh", name, "--channel=" + channel], _("Switching to %s…") % channel)
    return (True, _("Now following %s.") % channel) if ok else (False, err or _("Channel switch failed"))


def _job_gpu(name):
    ok, err = _connect_gpu(name)
    return (True, _("GPU connected.")) if ok else (False, err)


def _discard_ns(name):
    rc, out = _sudo(["/usr/lib/snapd/snap-discard-ns", name], timeout=60)
    return rc == 0, out


def _job_reset(name):
    """Drop the snap's mount namespace: the next start rebuilds it (GPU content, /android)."""
    stop_app(name)
    ok, err = _discard_ns(name)
    return (True, _("Environment reset. Open the app again.")) if ok else (False, err)


def _job_reset_all(_name):
    names = [s.get("name") for s in _installed_raw() if s.get("apps")]
    failed = [n for n in names if not _discard_ns(n)[0]]
    if failed:
        return False, _("Could not reset: %s") % ", ".join(failed)
    return True, _("All snap environments reset (%d).") % len(names)


def _job_nogpu(name):
    """Disconnect hybris: the snap falls back to its own Mesa (software rendering)."""
    rc, out = _sudo(["snap", "disconnect", name + ":" + GPU_PLUG])
    if rc != 0:
        return False, out
    _discard_ns(name)
    return True, _("GPU disconnected: the app now uses software rendering.")


def _job_devmode(name):
    ok, err = _run_change(name, ["refresh", "--devmode", name], _("Switching %s to devmode…") % name)
    return (True, _("Now in devmode.")) if ok else (False, err or _("Could not switch to devmode"))


# --------------------------------------------------------------------- job queue
_jobs = queue.Queue()
_pending = []           # names waiting or running, in order
_pending_lock = threading.Lock()


def _queued_names():
    with _pending_lock:
        return list(_pending)


def _send_queue():
    pyotherside.send("queue", _queued_names())


def _worker():
    while True:
        kind, name, args = _jobs.get()
        try:
            fn = {"install": _job_install, "remove": _job_remove, "refresh": _job_refresh,
                  "switch": _job_switch, "gpu": _job_gpu, "nogpu": _job_nogpu, "reset": _job_reset,
                  "reset-all": _job_reset_all, "devmode": _job_devmode}[kind]
            ok, msg = fn(name, *args)
        except Exception as e:  # never let the worker die
            ok, msg = False, str(e)
        _store_cache.clear()
        with _pending_lock:
            if name in _pending:
                _pending.remove(name)
        pyotherside.send("done", name, kind, ok, msg)
        _send_queue()


threading.Thread(target=_worker, daemon=True).start()
if pyotherside.__class__.__name__ != "_NoPyotherside":   # only inside the app, not in the unit tests
    threading.Thread(target=_migrate_launchers, daemon=True).start()


def enqueue(kind, name, args=None):
    """Queue a privileged action. Returns False if the password is missing or the snap is queued."""
    if _password is None:
        return False
    with _pending_lock:
        if name in _pending:
            return False
        _pending.append(name)
    _jobs.put((kind, name, list(args or [])))
    _send_queue()
    return True


def refresh_all():
    names = [u.get("name") for u in (snapd_get("/v2/find?select=refresh") or []) if u.get("name")]
    return [n for n in names if enqueue("refresh", n)]


def clear_cache():
    _store_cache.clear()
    return True


def app_dir():
    return APP_DIR
