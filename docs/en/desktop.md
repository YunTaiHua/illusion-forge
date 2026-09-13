# Desktop Edition

> [中文](../zh-CN/desktop.md) | English

IllusionForge desktop edition wraps the Web UI in Electron, bundles Python and Node.js runtimes, and distributes an NSIS installer for Windows 10/11 (x64/arm64).

## 📦 Download & Install

### Windows

1. Download `IllusionForge-Setup-<version>.exe` from the [GitHub Releases page](https://github.com/YunTaiHua/illusion-forge/releases).
2. Run the installer (choose an installation directory if desired).
3. The installer creates the Start Menu / desktop shortcuts automatically. Launch `IllusionForge` from them.

The installer registers the application identity (`AppUserModelID`) as part of the standard install — system notifications and the taskbar icon come from the shortcut created by the installer, with no runtime registration in-app. Config is written to `%USERPROFILE%\.illusion\`.

## 🪟 Windows Installer Notes

* **Standard install**: NSIS installer; Start Menu / desktop shortcuts (carrying the AppUserModelID) are maintained by the installer on install and uninstall.
* **Uninstall**: use Windows Settings → Apps, or the uninstaller created by the installer. To also clear config, delete `%USERPROFILE%\.illusion\`.
* **SmartScreen warning**: unsigned exe may be blocked on first launch — click "More info" → "Run anyway".
* **Migration**: config lives in the home directory, so reinstalling on another machine keeps/imports config independently.

## 🐍 Bundled Python / Node.js Runtimes

The desktop edition bundles an independent Python and Node.js runtime inside the app resources directory and **does not pollute the system PATH**.

### Detection Logic

| Runtime                  | Priority | Description                                                                   |
| ------------------------ | -------- | ----------------------------------------------------------------------------- |
| User's own Python / Node | First    | Used when `PATH` resolves a `python` / `node` meeting the version requirement |
| Bundled Python / Node    | Fallback | Used when the user's environment is missing or below the required version     |

### Exposure to LLM Tool Calls

* **User has their own environment**: the bundled Python only starts the backend; the bundled runtimes are not exposed to the user.

* **User has no environment**: the bundled Python / Node bin directories are prepended to the backend process's `PATH`, so LLM tool calls (e.g. bash tool running `python xxx.py` / `node xxx.js`) can use the bundled runtimes directly.

## 📌 Tray Behavior

| Action                        | Behavior                                               |
| ----------------------------- | ------------------------------------------------------ |
| Click window close button (×) | Hide window to system tray; app keeps running          |
| Click tray icon               | Show/hide main window                                  |
| Tray menu → Show/Hide main window | Toggle main window visibility                     |
| Tray menu → Open Terminal      | Open a terminal (cmd) with the bundled runtime        |
| Tray menu → Quit              | Truly exit: stop daemons, release port, quit app       |
| Launch again while running    | Focus the existing window; do not start a new instance |

## 🔄 Updates

### Automatic updates

The desktop edition ships with built-in auto-update through electron-updater + GitHub Releases (repo `YunTaiHua/illusion-forge`):

1. The app checks for updates after every startup; for long-running sessions it re-checks periodically.
2. When a new version is found, a **blinking download icon** appears next to the minimize button in the title bar; click it to start the download, with a progress ring shown while downloading.
3. Once downloaded, the icon turns into a **circle-check install-ready state**, clearly distinct from the download icon: click it to quit the app and run an **explicit install** (full installation progress is shown, and the app restarts automatically when done). Quitting the app normally does not trigger installation.
4. A system notification reminds you when the download finishes while the window is hidden in the tray.

Update packages are verified via SHA512 checksums. Updates run in place over the existing installation, and the `~/.illusion/` config directory is preserved across versions.

### Manual updates

Run the new installer over the current installation (`IllusionForge-Setup-<version>.exe`) to update in place.

## ⚠️ Notes

* **Unsigned**: no code signing on any platform — Windows triggers SmartScreen on first launch.
* **Slow first launch**: the bundled runtime takes a few seconds to initialize on first run.
* **Frameless window**: the desktop window uses `frame: false` with a custom title bar.
* **Backend process tree**: the backend process is killed with `taskkill /T /F` on quit.

## 🔧 Build Scripts

For developers building the desktop app from source:

```bash
# Build desktop app (Windows only; exits with an error on non-Windows)
python scripts/build_desktop.py --all

# Individual steps
python scripts/build_desktop.py --fetch    # Fetch Python + Node runtimes
python scripts/build_desktop.py --install  # Install runtimes to resources/
python scripts/build_desktop.py --icons    # Generate icon.ico + icon.png
python scripts/build_desktop.py --dist     # Build Electron distributable
```

Supporting scripts:

- `scripts/fetch_python.py` — downloads python-build-standalone Windows `install_only` tar.gz
- `scripts/fetch_node.py` — downloads Node.js Windows zip from nodejs.org
- `scripts/build_icons.py` — generates `icon.ico` and `icon.png`
- `scripts/sync_version.py` — syncs web frontend + desktop versions

## 📁 Desktop Project Structure

```
desktop/
├── electron-builder.yml   # NSIS target (win), appId com.illusionforge.desktop
├── src/
│   ├── main.ts            # Electron main process entry
│   ├── backend.ts         # Spawns `python -m illusion_forge forge --port <port>`
│   ├── runtime.ts         # platArch() → win-x64 / win-arm64
│   ├── tray.ts            # System tray icon + menu
│   ├── updater.ts         # electron-updater integration
│   └── ...
├── resources/
│   └── python/win-<arch>/  # Bundled Python runtime
│   └── node/win-<arch>/    # Bundled Node.js runtime
└── build/                  # Installer assets (icon.ico)
```

## 🔄 CI / Release

- `.github/workflows/ci.yml` — `windows-latest`: ruff + pytest
- `.github/workflows/release-desktop.yml` — triggered by `v*` tags on `windows-latest`; uploads `*.exe`, `latest*.yml`, and `*.blockmap` to GitHub Releases
