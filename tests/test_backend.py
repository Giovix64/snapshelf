"""Unit tests for the Snapshelf backend (no network, no snapd, no Lomiri needed).

Run with:  python3 -m unittest discover -s tests
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "qml"))
import backend as b  # noqa: E402

SNAP_YAML_GPU = """
name: demo
base: core24
apps:
  demo:
    command: bin/demo --flag
    plugs: [wayland, x11, opengl]
plugs:
  gpu-2404:
    interface: content
    target: $SNAP/gpu-2404
"""
SNAP_YAML_WAYLAND = """
name: wl
apps:
  wl:
    command: bin/wl
    plugs: [wayland, opengl]
"""


class CompatTest(unittest.TestCase):
    def test_levels(self):
        self.assertEqual(b.compat("core24", "strict")[0], "good")       # search: GPU unknown
        self.assertEqual(b.compat("core24", "strict", True)[0], "gpu")
        self.assertEqual(b.compat("core24", "strict", False)[0], "ok")
        self.assertEqual(b.compat("core22", "strict")[0], "ok")
        self.assertEqual(b.compat("core24", "classic", True)[0], "no")  # classic always wins

    def test_plugs_and_notes(self):
        self.assertIn("gpu-2404", b._yaml_plugs(SNAP_YAML_GPU))
        self.assertIn("content", b._yaml_plugs(SNAP_YAML_GPU))
        notes = b.notes_for(SNAP_YAML_WAYLAND, gpu=False, devmode=True)
        self.assertEqual(len(notes), 3)   # wayland only, software OpenGL, devmode
        self.assertEqual(b.notes_for(SNAP_YAML_GPU, gpu=True, devmode=False), [])

    def test_helpers(self):
        self.assertEqual(b.human_size(101363712), "101.4 MB")
        self.assertEqual(b.human_size(None), "")
        self.assertEqual(b._channel_label({"track": "latest", "risk": "edge"}), "edge")
        self.assertEqual(b._channel_label({"track": "2.0", "risk": "stable"}), "2.0/stable")


class SearchTest(unittest.TestCase):
    RESULTS = {"results": [
        {"name": "a", "snap": {"title": "A"}, "revision": {"base": "core24", "confinement": "strict", "type": "app"}},
        {"name": "c", "snap": {"title": "C"}, "revision": {"base": "core22", "confinement": "classic", "type": "app"}},
        {"name": "k", "snap": {"title": "K"}, "revision": {"base": "core22", "confinement": "strict", "type": "kernel"}},
    ]}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = [mock.patch.object(b, "_store_get", return_value=self.RESULTS),
                  mock.patch.object(b, "snapd_get", side_effect=lambda path: [] if "refresh" in path else None),
                  mock.patch.object(b, "_installed_raw", return_value=[{"name": "a"}]),
                  mock.patch.object(b, "SETTINGS_FILE", os.path.join(self.tmp.name, "s.json"))]
        for p in self.p:
            p.start()

    def tearDown(self):
        for p in self.p:
            p.stop()
        self.tmp.cleanup()

    def test_search_filters_and_marks(self):
        r = b.search("x")
        self.assertEqual([i["name"] for i in r["items"]], ["a", "c"])   # kernel snap dropped
        self.assertTrue(r["items"][0]["installed"])
        b.set_setting("hide_unsupported", True)
        self.assertEqual([i["name"] for i in b.search("x")["items"]], ["a"])

    def test_search_requests_arm64(self):
        b.search("gimp")
        url = b._store_get.call_args[0][0]
        self.assertIn("architecture=arm64", url)
        self.assertIn("q=gimp", url)

    def test_store_error(self):
        with mock.patch.object(b, "_store_get", side_effect=OSError("offline")):
            r = b.search("x")
        self.assertEqual(r["items"], [])
        self.assertIn("offline", r["error"])


class DesktopTest(unittest.TestCase):
    """Launcher pinning and compatibility mode on a fake filesystem."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = self.tmp.name
        self.snapdir = os.path.join(t, "snapd")
        self.userdir = os.path.join(t, "apps")
        os.makedirs(self.snapdir)
        with open(os.path.join(self.snapdir, "demo_demo.desktop"), "w") as f:
            f.write("[Desktop Entry]\nName=Demo\nExec=/snap/bin/demo\nIcon=/snap/demo/41/meta/gui/demo.png\n")
        self.items = ["appid://other"]
        self.p = [mock.patch.object(b, "SNAP_DESKTOP_DIR", self.snapdir),
                  mock.patch.object(b, "USER_APPS_DIR", self.userdir),
                  mock.patch.object(b, "_launcher_items", side_effect=lambda: list(self.items)),
                  mock.patch.object(b, "_set_launcher_items", side_effect=self._set),
                  mock.patch.object(b, "_app_command", return_value="bin/demo --flag"),
                  mock.patch.object(b, "_helpers", return_value=("/x/nabu-xland", "/m")),
                  mock.patch.object(b, "_connected_original_ifaces", side_effect=lambda n: list(self.ifaces))]
        self.ifaces = ["wayland"]          # the snap's own launcher is visible in Lomiri
        for p in self.p:
            p.start()

    def _set(self, items):
        self.items = list(items)

    def tearDown(self):
        for p in self.p:
            p.stop()
        self.tmp.cleanup()

    def test_apps_icon_uses_current(self):
        apps = b._snap_apps("demo")
        self.assertEqual(apps[0]["id"], "demo_demo")
        self.assertEqual(apps[0]["icon"], "/snap/demo/current/meta/gui/demo.png")

    def test_pin_unpin(self):
        self.assertTrue(b.pin("demo", True))
        self.assertEqual(self.items, ["appid://other", "appid://demo_demo"])
        self.assertFalse(b.pin("demo", False))
        self.assertEqual(self.items, ["appid://other"])

    def test_compat_mode_swaps_pinned_launcher(self):
        b.pin("demo", True)
        r = b.set_compat_mode("demo", True)
        self.assertTrue(r["enabled"])
        path = os.path.join(self.userdir, "snapshelf-x11-demo.demo.desktop")
        text = open(path).read()
        self.assertIn("Name=Demo (GPU)", text)
        self.assertIn("snapshelf-run x11-gpu demo bin/demo --flag", text)
        self.assertIn("Exec=/x/nabu-xland --host", text)                 # no X keyboard helper here
        with mock.patch.object(b, "_xkbd", return_value="/x/nabu-xkbd"):
            b.set_launch_mode("demo", "x11-gpu")
        self.assertIn("Exec=env NABU_XLAND_KBD=1 /x/nabu-xland --host", open(path).read())
        self.assertEqual(self.items, ["appid://other", "appid://snapshelf-x11-demo.demo"])
        self.assertEqual(b.open_app("demo"), "snapshelf-x11-demo.demo")
        b.set_compat_mode("demo", False)
        self.assertFalse(os.path.exists(path))
        self.assertEqual(self.items, ["appid://other", "appid://demo_demo"])


    def test_launch_modes(self):
        self.assertEqual(b.launch_mode("demo"), "default")
        r = b.set_launch_mode("demo", "wl-safe")
        self.assertEqual(r["mode"], "wl-safe")
        text = open(os.path.join(self.userdir, "snapshelf-safe-demo.demo.desktop")).read()
        self.assertIn("Name=Demo (safe)", text)
        self.assertNotIn("nabu-xland", text)               # Wayland mode: no nested X server
        b.set_launch_mode("demo", "x11-sw")
        self.assertEqual(os.listdir(self.userdir), ["snapshelf-x11sw-demo.demo.desktop"])  # one mode at a time
        self.assertEqual(b.set_launch_mode("demo", "bogus")["ok"], False)

    def test_known_fix(self):
        with mock.patch.dict(b.KNOWN_FIXES, {"demo": "x11-gpu"}):
            self.assertEqual(b.apply_known_fix("demo"), "x11-gpu")
            self.assertEqual(b.apply_known_fix("demo"), "")  # already applied

    def test_mode_unavailable_without_helpers(self):
        with mock.patch.object(b, "_helpers", return_value=("", "")):
            r = b.set_launch_mode("demo", "x11-gpu")
        self.assertFalse(r["ok"])
        self.assertEqual(r["mode"], "default")


    def test_migrate_old_launcher_names(self):
        os.makedirs(self.userdir, exist_ok=True)
        for old in ("snapshelf-x11-demo_demo.desktop", "snapshelf-safe-foo--foo.desktop"):
            open(os.path.join(self.userdir, old), "w").close()
        self.items = ["appid://snapshelf-x11-demo_demo", "appid://snapshelf-safe-foo--foo"]
        b._migrate_launchers()
        # demo is rewritten in its mode; foo is not installed any more, so its launcher goes away
        self.assertEqual(sorted(os.listdir(self.userdir)), ["snapshelf-x11-demo.demo.desktop"])
        self.assertEqual(self.items, ["appid://snapshelf-x11-demo.demo"])   # stale pin of foo dropped

    def test_hidden_original_drops_suffix(self):
        self.ifaces = []                   # unity7/wayland/lomiri disconnected: original hidden
        self.assertTrue(b.original_hidden("demo"))
        b.set_launch_mode("demo", "x11-gpu")
        text = open(os.path.join(self.userdir, "snapshelf-x11-demo.demo.desktop")).read()
        self.assertIn("Name=Demo\n", text)

    def test_hide_needs_x11_mode(self):
        ok, msg = b._hide_original("demo")      # still in the default mode
        self.assertFalse(ok)

    def test_launchers_in_use(self):
        b.set_launch_mode("demo", "x11-sw")
        self.assertEqual(b._launchers_in_use(), [("demo", "x11-sw")])

    def test_ids_have_no_lomiri_separators(self):
        b.set_launch_mode("demo", "x11-gpu")
        for f in os.listdir(self.userdir):
            self.assertNotIn("_", f)
            self.assertNotIn("--", f)


class DiagnoseTest(unittest.TestCase):
    def test_rules(self):
        log = ["qt.qpa.wayland: eglSwapBuffers failed with 0x300d", "Cannot find EGLConfig, returning null config",
               'dlopen failed: library "libEGL.so" not found']
        with mock.patch.object(b, "app_log", return_value=log), \
                mock.patch.object(b, "launch_mode", return_value="default"):
            fixes = [s["fix"] for s in b.diagnose("x")["suggestions"]]
        self.assertEqual(fixes, ["reexec", "x11-gpu"])     # one suggestion per fix, in rule order

    def test_applied_fix_not_suggested(self):
        with mock.patch.object(b, "app_log", return_value=["Cannot find EGLConfig"]), \
                mock.patch.object(b, "launch_mode", return_value="x11-gpu"):
            r = b.diagnose("x")
        self.assertEqual([s["fix"] for s in r["suggestions"]], [""])   # "no known problem"

    def test_empty_log(self):
        with mock.patch.object(b, "app_log", return_value=[]), mock.patch.object(b, "launch_mode", return_value="default"):
            self.assertEqual(b.diagnose("x")["suggestions"][0]["fix"], "")


class QueueTest(unittest.TestCase):
    def test_enqueue_needs_password_and_deduplicates(self):
        with mock.patch.object(b, "_password", None):
            self.assertFalse(b.enqueue("refresh", "x"))
        done = []
        with mock.patch.object(b, "_password", "pw"), \
                mock.patch.dict(b.__dict__, {"_job_refresh": lambda name: (done.append(name) or (True, "ok"))}), \
                mock.patch.object(b.pyotherside, "send", create=True):
            with b._pending_lock:          # hold the worker until both calls are queued
                b._pending.append("y")
            self.assertFalse(b.enqueue("refresh", "y"))   # already queued
            with b._pending_lock:
                b._pending.remove("y")


if __name__ == "__main__":
    unittest.main()
