# Building the Habit Quest installer

This is the technical side: how to turn this repository into something another
person can install on their own Windows PC, and how to do it again after you add
a feature.

The whole process is one command. It produces an installer (with a desktop icon)
and a portable zip.

```
powershell -ExecutionPolicy Bypass -File scripts\build-install.ps1
```

You do not need to remember any other step. The script is idempotent: run it
again after any code change and you get a fresh set of installers.

---

## What you get

Everything lands in `desktop\release\`:

| File | What it is |
|---|---|
| `Habit-Quest-Setup-<version>.exe` | The installer. Installs per-user (no admin prompt), creates a **desktop icon** and a Start-menu entry, and offers to launch the app when it finishes. |
| `Habit-Quest-<version>-win-x64.zip` | The same app, unpacked and portable. Unzip anywhere, run `Habit Quest.exe`. No install, no registry. |
| `Habit-Quest-<version>-windows-x64.zip` | The **hand-off bundle**: the installer, the portable zip, both documents and a `VERSION.txt`, all in one zip. This is the file to send someone. |
| `SHA256SUMS.txt` | Checksums, so a download can be verified. |

Expect roughly **125 MB** for the installer, **160 MB** for the portable zip and
**280 MB** for the hand-off bundle — Electron's engine is most of it. A full
build takes about four minutes; the first one is slightly slower while it
downloads its tooling.

---

## What the person installing it needs

Only this:

- **Windows 10 or 11, 64-bit**
- **About 500 MB of disk space**
- Permission to install software in their own user account (no administrator
  rights needed)

**They do not need Python. They do not need Node.js. They do not need an
internet connection** — the game runs entirely offline.

That is the point of the build: the Python backend is compiled into a single
executable (`habit-quest-backend.exe`) with PyInstaller, and Electron ships its
own Chromium, so the installed app is self-contained.

## What the machine building it needs

- **Windows 10 or 11, 64-bit** (this is a Windows build; see *Other platforms*)
- **Node.js 18 or newer** — <https://nodejs.org/> (built and tested with Node 24)
- **Python 3.10 or newer** — <https://www.python.org/downloads/windows/>. Tick
  **"Add python.exe to PATH"** in the installer.
- **About 2 GB of free disk space** while building
- **Internet access on the first build**, to download `electron-builder`,
  `PyInstaller` and the NSIS installer tooling. Later builds reuse the caches in
  `build\`, `desktop\node_modules` and `%LOCALAPPDATA%\electron-builder\Cache`.

Nothing is installed system-wide. The build tooling lives in:

```
build\venv-backend\          throw-away Python environment (PyInstaller)
build\pyinstaller-work\      PyInstaller scratch space
desktop\node_modules\        Electron + electron-builder
desktop\backend-dist\        the compiled backend executable
desktop\release\             the finished installers
```

All of these are ignored by git except the source that feeds them.

---

## What the script does, step by step

1. **Checks the tools.** Node ≥ 18 and a Python ≥ 3.10 on PATH. If either is
   missing it stops with the download link rather than failing halfway through.
2. **Bumps the version** (only with `-Bump`, see below).
3. **Compiles the backend.** Creates `build\venv-backend`, installs PyInstaller
   into it once, then freezes `desktop\backend_entry.py` into
   `desktop\backend-dist\habit-quest-backend.exe`. The `static\` folder (the
   whole front end) is embedded inside the executable.
4. **Smoke-tests that executable.** It starts it, waits for the port handshake,
   calls `/api/health`, `/api/state` and `/` over HTTP, then shuts it down. A
   broken backend fails the build instead of shipping. (`desktop\smoke-backend.js`,
   runs on plain Node — no Electron.)
5. **Installs the desktop dependencies** with `npm install` in `desktop\`.
6. **Packages the app** with electron-builder, producing the NSIS installer and
   the portable zip.
7. **Assembles the distribution zip** with the installer, the portable zip and
   the docs, and writes `SHA256SUMS.txt`. The hand-off zip is built in a
   per-run folder under `%TEMP%` and deleted there afterwards, so the repository
   never contains half-finished packaging and a rerun always starts clean.

The build prints each step, the backend size, and a summary with file sizes and
the total time.

### First build vs. later builds

The first run downloads Electron's packaging tools and installs PyInstaller, so
it takes several minutes. Subsequent runs reuse all of it; most of the time is
spent in PyInstaller and in compressing the installer.

---

## Rebuilding after you add a feature

```powershell
# 1. change the code (Python, static/, whatever)
# 2. rebuild
powershell -ExecutionPolicy Bypass -File scripts\build-install.ps1
```

That is all. Two things to know:

- **Close Habit Quest first.** Windows locks the `.exe` while it runs, so
  packaging fails if the app is open (the script will tell you).
- **Bump the version when you are giving the build to someone**, so two
  installers are distinguishable:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build-install.ps1 -Bump patch
```

`-Bump` accepts `patch`, `minor` or `major` and updates `desktop\package.json`
(and the lockfile) before building. The version string appears in every
artifact name, in `VERSION.txt`, and in Windows' *Add or remove programs*.

### Options

| Flag | Effect |
|---|---|
| `-Bump patch\|minor\|major` | Raise the version before building. |
| `-SkipBackend` | Reuse the existing compiled backend. The result needs Python 3.10+ on the target machine — useful for a fast UI-only test build, not for handing out. |
| `-SkipInstall` | Skip `npm install` when `node_modules` is already current. |
| `-NoZip` | Leave the files loose in `desktop\release\` without the extra distribution zip. |

---

## How a packaged app is put together

```
Habit Quest.exe                  Electron shell (main.js + backend.js)
resources\
  app\                           the Electron JavaScript (asar disabled on purpose)
  habitquest\*.py                the Python game, un-compiled
  static\                        the front end
  backend\habit-quest-backend.exe  the compiled Python backend
```

Why this shape:

- **One origin, no proxy.** `main.js` starts the backend on a *free* port, waits
  for it to print `{"port": ...}` on stdout, then loads
  `http://127.0.0.1:<port>/` into the window. The UI and the API share an
  origin, so there is no CORS layer and no second copy of the front end.
- **`asar` is off.** The Python fallback and the static files are read from
  ordinary files on disk; packing them into Electron's archive would break both.
- **Two ways to start the backend.** If `resources\backend\habit-quest-backend.exe`
  exists it is used directly (no Python needed). If it does not — a
  `-SkipBackend` build — the shell runs `python -m habitquest.desktop` from
  `resources\`, which is why the `.py` sources are shipped as well.
- **Clean shutdown.** Closing the window closes the backend's stdin; the backend
  treats EOF as "quit", closes the SQLite file properly and exits, so the save is
  never truncated. A crashed shell cannot leave an orphaned server behind.
- **One instance at a time.** A second launch focuses the first window instead of
  fighting over the save file.

### Where the installed app keeps your save

```
%APPDATA%\Habit Quest\habitquest.db        the whole game state
%APPDATA%\Habit Quest\sounds\              a custom alarm, if one was uploaded
```

This is deliberately outside the install folder, so uninstalling or installing a
new version never touches the hero. (The `python app.py` version keeps its save
next to `app.py` instead — the two are independent.)

---

## Verifying a build before you hand it over

The build already smoke-tests the backend. For a full check, do this once per
release:

1. Run `Habit-Quest-Setup-<version>.exe` on a machine that has **no Python**.
   If it starts and you can complete a quest, the bundling worked.
2. Confirm the desktop icon exists and opens the app.
3. Unzip the portable zip somewhere else and run `Habit Quest.exe` from there.
4. Close the window, reopen: your hero, your gold and your quests are still
   there.

`npm run verify` (in `desktop\`) is a developer check that boots the shell
headlessly against the source tree. It does not test the installer.

---

## Troubleshooting

**"Windows protected your PC" / SmartScreen.** Expected for an unsigned
installer. The user clicks **More info → Run anyway**. To remove the warning you
need a code-signing certificate and one line in `desktop\package.json`:

```json
"win": { "certificateFile": "cert.pfx", "certificatePassword": "…" }
```

Or set the `CSC_LINK` / `CSC_KEY_PASSWORD` environment variables. Signing is the
only fix; nothing in the build can avoid the warning.

**Antivirus flags the installer or the backend.** PyInstaller executables are a
common false positive. The backend is a normal Python program compiled to an
`.exe`; submitting it to the vendor as a false positive is the usual remedy.

**`python was not found on PATH`.** Reinstall Python with *Add python.exe to
PATH* ticked, or build with `-SkipBackend` if you only need a test build.

**`npm install` fails.** Corporate proxy or offline machine — set `HTTP_PROXY` /
`HTTPS_PROXY`, or copy a populated `desktop\node_modules` and `desktop\package-lock.json`
from another machine and use `-SkipInstall`.

**electron-builder download failures.** Its cache is
`%LOCALAPPDATA%\electron-builder\Cache`; delete it and rebuild if a download was
interrupted. The downloads are cached by Electron version, so a rebuild usually
needs no network at all.

**"The app is still running" / access denied while packaging.** Close Habit
Quest (check the notification area) and rebuild.

**`Expected build output is missing`.** Open the electron-builder output above
it; the usual causes are a missing icon (`desktop\build\icon.png`) or a Node
version below 18.

**The zip step fails with `being used by another process`.** Almost always the
virus scanner reading the 160 MB portable zip that was copied a second earlier,
or an Explorer window previewing it. The build now waits and retries five times
(two seconds apart) before giving up, so this is rare - if it still happens, run
the build again. Every earlier step is cached (PyInstaller, npm, electron-builder
downloads), so a retry only redoes the last minute or so. Closing Explorer
windows on `desktop\release` makes it certain.

**No half-finished zip after a failure.** The archive is written under a
`.partial` name and only renamed to `Habit-Quest-<version>-windows-x64.zip` once
it is complete and readable, so an interrupted bundle step never leaves a
corrupt file for you to hand out by mistake.

**The installed app opens but says "Habit Quest could not start".** That dialog
comes from the shell when the backend cannot be launched. A build made with
`-SkipBackend` needs Python on that machine; a normal build that ships
`resources\backend\habit-quest-backend.exe` does not.

---

## Other platforms

The packaging config targets Windows x64 only. The Electron shell itself is
cross-platform (`main.js` picks `habit-quest-backend` without `.exe` on macOS and
Linux), so a macOS or Linux build is a matter of adding the target:

- macOS: `"mac": { "target": ["dmg"], "icon": "build/icon.png" }` and run
  electron-builder on a Mac (code signing is effectively required to distribute).
- Linux: `"linux": { "target": ["AppImage"], "icon": "build/icon.png" }`.

The frozen backend has to be built on the platform it runs on, so each platform
needs its own build machine — `scripts\build-install.ps1` is Windows-only. The
equivalent commands are `python -m PyInstaller …` (see the script for the exact
arguments) followed by `npx electron-builder --mac` or `--linux`.

Building the icon:

```
python scripts\make-icon.py
```

That redraws `desktop\build\icon.png` from code (no image libraries needed) if
you ever want different artwork; the packager derives every icon size from it.

---

## File map for the packaging bits

| Path | Role |
|---|---|
| `scripts\build-install.ps1` | The build. Everything above happens here. |
| `desktop\package.json` | Electron app metadata + the `build` block electron-builder reads (app id, icon, targets, NSIS options, which folders are bundled). |
| `desktop\main.js` | Window, lifecycle, shutdown; chooses the right project root when packaged. |
| `desktop\backend.js` | Starts and supervises the backend, source or frozen. |
| `desktop\backend_entry.py` | The frozen backend's entry point. |
| `desktop\smoke-backend.js` | HTTP smoke test for the compiled backend. |
| `desktop\verify.js` | Headless check of the window against the source tree. |
| `desktop\build\icon.png` | App icon (generated by `scripts\make-icon.py`). |
| `desktop\release\` | Build output. |
