# RepBuddy desktop

The Windows app contains Electron, the built React interface, a packaged Python
tracker with its pose model, and PostgreSQL 18. Users do not need to install
Python, Node, Docker, or a separate database server.

## Install and open

Run `RepBuddy-Setup-0.1.0-x64.exe` from the `release` folder. The installer adds
Start menu and desktop shortcuts. Open RepBuddy from either shortcut.

This build targets 64 bit Windows 10 and Windows 11. It is unsigned, so Windows
may show an unknown publisher or reputation warning. A public release should
be signed with the project owner's signing certificate.

On first launch, the loading screen stays visible while the app creates its
private database. The camera stays off until you start a workout or calibration.
Closing the window stops the tracker and private database after pending saves
finish. Only one copy of the desktop app can run at a time.

## Your workout history

Desktop data lives in `%APPDATA%\RepBuddy`. The database files are in
`postgres-18`, with its connection password in `database.json`. Keep that file
private. To make a full local backup, close RepBuddy and copy this entire folder.
Uninstalling the app keeps this data so reinstalling can recover your history.

The desktop database is separate from the development database configured in
`.env`. Existing development workouts are not copied into an installer or
automatically imported. The app opens its private database only on localhost
and chooses unused ports, so it can run alongside a system PostgreSQL service.

Logs are in `desktop.log` and `postgres.log` inside the same data folder.
If startup fails, close and reopen RepBuddy, then check these logs. Do not delete
the database folder to resolve an error without first making a backup.

## Build an installer

Build on Windows using Node 22.12 or newer, Python 3.11, and PostgreSQL 18.
PostgreSQL is needed on the build computer only so its redistributable runtime
can be included. Its Windows service does not need to be running for this build.

```powershell
npm ci
npm --prefix frontend ci
.venv\Scripts\python.exe -m pip install -r requirements-build.txt
npm run desktop:build
npm run desktop:smoke
```

If PostgreSQL is installed somewhere else, set its program folder first.

```powershell
$env:REPBUDDY_POSTGRES_HOME = 'D:\PostgreSQL\18'
npm run desktop:build
```

The installer is written to `release`. The unpacked application is in
`release\win-unpacked`. Share the installer, rather than the single executable
inside the unpacked folder. It needs its accompanying resources.

`desktop:smoke` starts the packaged app with a new test data folder, loads the
pose model without using a webcam, checks the rendered interface and live
tracker connection, then checks database shutdown. Logs and a screenshot are
left under `build\packaged-smoke-*`. This check does not install the app or
change normal desktop history.

After `desktop:prepare`, `desktop:start` opens the Electron shell from source
using the packaged backend resources. Run `desktop:prepare` again after changing
Python or frontend code. `npm run dev` remains available for browser development.

The build includes only program files, models, migrations, frontend assets,
and dependency notices. It does not include `.env`, database files, backups,
or the project's virtual environment. Bump the root package version before
creating a new release. PostgreSQL major version upgrades require a separate
database migration plan and must not replace an existing cluster in place.

## Implementation

Electron starts the bundled tracker as a hidden child process. Python serves
the React build and API on one local port. Electron adds a random session token
to requests, including video and WebSockets. Requests without that token are
rejected. The renderer has no Node access, uses context isolation and sandboxing,
and cannot open external windows or navigate to another origin.

The implementation follows [Electron's security guidance](https://www.electronjs.org/docs/latest/tutorial/security).
Python is bundled using [PyInstaller](https://pyinstaller.org/en/stable/usage.html),
and the Windows installer is built with [electron-builder](https://www.electron.build/nsis/).
PostgreSQL and dependency notices are included with the runtime, including the
[PostgreSQL licence](https://www.postgresql.org/about/licence/).
