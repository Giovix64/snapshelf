# Snapshelf

**Find and install arm64 snaps that work on Ubuntu Touch.**

Snapshelf is a small native app (QML / Lomiri + Python) for Ubuntu Touch 24.04. It browses the Snap Store
for **arm64** snaps, tells you how well each one will work on your device, and installs, updates and removes
them through snapd.

> Not affiliated with Canonical or the Snap Store. This project was created in cooperation with an AI assistant.
> It was developed and tested on a Xiaomi Pad 5 (`nabu`) running the
> [Ubuntu Touch nabu port](https://github.com/Giovix64/ubuntu-touch-xiaomi-nabu).

## Features

- **Discover**: featured snaps, the Store categories and search-as-you-type. Only snaps that have an arm64 build are shown.
- **Compatibility badge** for every snap:

  | Badge | Meaning |
  |---|---|
  | `GPU` | the snap plugs `gpu-2404`: hardware acceleration through [`hybris-2404`](https://snapcraft.io/hybris-2404) |
  | `core24` | core24 snap, GPU acceleration possible (shown before the details are loaded) |
  | `works` | runs with software rendering |
  | `not supported` | classic confinement |

  The details page also warns about Wayland-only apps and OpenGL apps without hybris.
- **Install / remove / update** with live progress, a queue (one snapd change at a time) and *Update all*.
  - Channel selection (stable, candidate, beta, edge, other tracks) and switching channel of an installed snap.
  - Snaps that support it get the GPU connected automatically (`snap connect <snap>:gpu-2404 hybris-2404:gpu-2404`);
    hybris-2404 is installed first if needed.
- **Launcher**: optionally pin new apps to the Lomiri sidebar, or pin/unpin any installed snap.
- **Troubleshooting** for every installed app:
  - **Launch modes**. Each mode adds an extra launcher next to the original one, because Lomiri lists snap apps
    straight from snapd:

    | Mode | Launcher | What it does |
    |---|---|---|
    | X11 + GPU (Turnip) | *App* (GPU) | landscape nested X server, Mesa Turnip/Zink on KGSL instead of libhybris. Fixes empty or grey windows and EGL errors of Qt6, wgpu/Vulkan and GTK4 apps on Mir 1.8 (Telegram, PdfCraft) |
    | X11, software | *App* (X11) | nested X server, software rendering |
    | Wayland, software | *App* (safe) | stays on Wayland and forces Qt, GTK, wgpu and SDL to software rendering |

    The X11 modes need the helpers of the nabu port (`nabu-xland`, and a Mesa Turnip build for the GPU mode);
    unavailable modes say why.
  - **Diagnose** reads the app's recent log and recognises known problems:
    - "Cannot find EGLConfig", `eglSwapBuffers` failures, lost context or device, glutin errors;
    - `libEGL.so not found`, a missing GPU wrapper;
    - no Wayland or X display, crashes, AppArmor denials.

    For each one it suggests a fix you can apply with one tap.
  - **Repairs**: stop the app, reset the snap environment (mount namespace), connect or disconnect the hybris GPU,
    switch to devmode.
  - **Hide the original icon**: when an X11 launch mode works, the snap's own launcher can be hidden
    (Snapshelf disconnects the `unity7`/`wayland`/`lomiri` plugs Lomiri uses to list snap apps; the snap stays in
    devmode, so it keeps working in X11) and the working launcher gets the app's normal name.
  - In the X11 modes the app window is kept on the whole screen (`bin/snapshelf-xmax`, plain libX11 via ctypes):
    apps with their own frame (Telegram) otherwise stay small in the middle. If the port's X keyboard helper is
    present, the on-screen keyboard is started with the app and the window is kept above it.
  - **Known fixes**, applied automatically after installing: snaps known to need a launch mode (telegram-desktop,
    pdfcraft) get it straight away.
- **System checks** with one-tap fixes:
  - hybris-2404 installed;
  - "Reset all snap environments";
  - `SNAP_REEXEC=0`, which keeps `snap` on the Ubuntu Touch snapd tools. Their snap-confine is the one that mounts
    `/android` for libhybris inside snaps. Without it, GPU snaps fail with `libEGL.so not found` once the snapd snap
    is installed.
- **English and Italian.**

## Privacy and security

- The app uses the `unconfined` AppArmor template. It needs to talk to snapd, run `sudo snap …`, change Lomiri
  settings and write launchers.
- Installing needs your password (the screen-lock passcode). It is checked with `sudo -v` and kept **only in memory**
  while the app is open. *Settings → Forget the password* drops it.
- Store requests go to `api.snapcraft.io` with the standard snapd headers (series 16, arm64). No accounts, no telemetry.
- Snaps are installed in **devmode** by default, because kernels without the BPF device cgroup (such as 4.14) cannot
  start strict snaps. This can be turned off in the settings.

## Build

```sh
./build.sh                  # needs gettext and the `click` tool (on Ubuntu Touch), or:
clickable build             # with Clickable
```

Install on the device:

```sh
sudo click install --user=phablet --allow-unauthenticated dist/snapshelf.giovix64_*_all.click
```

Tests (no network or device needed):

```sh
python3 -m unittest discover -s tests
```

Translations live in `po/`. Run `./update-translations.sh` after changing strings, then edit `po/<lang>.po`.

## Layout

| Path | Content |
|---|---|
| `qml/Main.qml` | app window, shared state, action queue and Python bridge |
| `qml/pages/` | Browse (discover/installed/updates), Detail, Settings, dialogs |
| `qml/components/` | list delegate, badge and settings rows |
| `qml/backend.py` | Store API, snapd REST, queue, launcher, compatibility mode, system checks |
| `bin/snapshelf-run` | launch-mode runner (`x11-gpu`, `x11-sw`, `wl-safe`) inside the snap environment |
| `bin/snapshelf-xmax` | keeps the app's main window on the whole nested X screen, above the X keyboard |
| `po/` | translation template and Italian translation |
| `tests/` | unit tests for the backend |

## License

GPL-3.0, see [LICENSE](LICENSE).
