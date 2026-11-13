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
- **Compatibility mode (X11 + Turnip)**, for snaps whose window stays empty or grey on Mir 1.8 (for example
  wgpu/Vulkan apps). Snapshelf creates an extra "*App* (GPU)" launcher that runs the snap in a landscape
  nested X server with the Mesa Turnip driver on KGSL instead of libhybris. This needs the helpers of the nabu port
  (`nabu-xland` and a Mesa Turnip build); otherwise the option is disabled.
- **System checks** with one-tap fixes:
  - hybris-2404 installed;
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
| `bin/snapshelf-x11-run` | compatibility-mode runner (X11 + Mesa Turnip/Zink inside the snap environment) |
| `po/` | translation template and Italian translation |
| `tests/` | unit tests for the backend |

## License

GPL-3.0, see [LICENSE](LICENSE).
