# RepBuddy

RepBuddy is a desktop app that counts push-ups using your webcam. Face the
camera, choose your reps, sets, and rest time, then follow your progress with
a live preview. Completed sets are saved so you can look back at your workouts.

The interface uses Electron, React, and TypeScript. Python handles pose tracking,
and PostgreSQL stores your history. Everything runs locally on your computer.

See the [changelog](CHANGELOG.md) for recent updates and what's planned next.

## Install the desktop app

You'll need **64-bit Windows 10 or Windows 11** and a webcam. The installer
includes Python, the pose model, and PostgreSQL. You don't need to install
Python, Node.js, Docker, or a database yourself.

1. Open `RepBuddy-Setup-0.1.0-x64.exe` and follow the installer steps.
2. Choose where to install the app, then finish the installation.
3. Open **RepBuddy** from the Start menu or desktop shortcut.
4. Wait for the workout screen. The first launch takes longer while the app
   sets up its database. The camera stays off until you start a workout or
   calibration.

The installer is generated in the project's `release` folder. It isn't included
when you clone this repository or download the source ZIP. If you don't already
have the installer, follow [Build the desktop app](#build-the-desktop-app).

This build is unsigned, so Windows may show an unknown publisher or reputation
warning. Only run an installer from a source you trust.

To quit, close the app window. RepBuddy stops its camera, Python tracker, and
private database automatically. Saved sets remain available next time you open
it. Unfinished workout progress does not carry over after closing the app.

## Using the tracker

1. Choose your webcam from the **Camera** menu. Use **Refresh** after plugging
   in a camera, and stop the current camera before switching devices.
2. Place your camera in front of you and keep it roughly level. Use enough light
   for the camera to see your arms and torso clearly.
3. Make sure your shoulders, elbows, wrists, and hips stay visible throughout
   the movement. Your knees and ankles can be out of frame.
4. Choose 5, 10, 15, or 20 reps per set, between 1 and 10 sets, and a rest
   time between sets. Rest options range from no rest to five minutes.
   Press **Start workout**. The preview opens with a five-second countdown.
   The timer and rep counter start after it ends. **Cancel countdown** keeps
   the preview on without starting the set.
5. Get into a plank with your arms extended. Lower yourself, then push back up
   to complete a rep.

The preview shows your tracked joints and elbow angles. The status below it
lets you know when the tracker needs you to adjust your position.

### Calibration

You can use **Calibrate** before starting a workout. Hold the starting plank,
lower into a full push-up, then return to the top when prompted. This learns
separate angle limits for each arm within a fixed range. The practice rep
doesn't count toward your goal, start the timer, or create a history entry.
Calibration is optional, and **Cancel** keeps your previous settings.

Calibration stays available for the same camera while the app is open,
including after a reset. Switching cameras or closing the app clears it.
Recalibrate after moving your camera, or choose **Use defaults** to restore the
original angle limits.
Reset an unfinished workout before changing its calibration.

### Workout controls

- **Pause** stops counting and pauses the timer, but keeps the camera on.
- **Resume** gives you another five-second countdown before continuing the set.
  Start with your arms extended again.
- **Stop camera** turns off the webcam and keeps your rep count and time while
  the app stays open.
- **Pause rest** freezes the rest timer. **Resume rest** continues from the
  remaining time. Stopping the camera also pauses rest.
- **Skip rest** moves to the next set's five-second countdown once the last set
  has saved. Choosing no rest still gives you that countdown.
- **Reset** is the circular arrow beside the main button. It clears workout
  progress and turns off the camera. Use it before changing reps, sets, or rest.
  It keeps your settings and saved history.

Reaching the rep goal saves that set to PostgreSQL and starts the rest timer.
The next set begins automatically after rest and a five-second countdown.
After the final set, the workout ends without another rest. Press **New workout**
to repeat the same plan. Active time includes exercise across all sets and
excludes rest, pauses, and countdowns. Plan settings last until you close the app.

## Workout history

The history panel shows completed sets with their date, reps, goal, and active
time. It also shows total sets, total reps, your best set, and this week's reps.
Dates use your local time; weekly totals run from Monday to Sunday in UTC.
Use **Load older sets** to see more records.

Only sets that reach their goal are saved. Pausing, stopping the camera, or
resetting an unfinished set doesn't create a history entry. Rest and countdown time
isn't included in the saved duration. Camera images aren't stored.

If a save fails, keep the app open and press **Retry saving set** once PostgreSQL
is available again. Starting a new set and resetting are disabled until that
save succeeds. Retrying or reconnecting won't duplicate an already saved set.

### Where your data is saved

The desktop app saves its data in `%APPDATA%\RepBuddy`. Paste that path into
File Explorer's address bar to open it. To back up your history, close RepBuddy,
wait for it to finish shutting down, and copy the entire folder somewhere safe.
The `database.json` file contains the local database password, so keep it private.

Uninstalling RepBuddy keeps this folder. Reinstalling the app can reuse your
saved history. The desktop database is separate from the database used when
running the source code, so development workouts won't appear automatically.

## Troubleshooting

- **The camera won't open.** Close other apps using it, check Windows camera
  permissions for desktop apps, then refresh the camera list in RepBuddy.
- **Reps aren't counting.** Keep your shoulders, elbows, wrists, and hips visible
  for the full movement. Start with straight arms, lower yourself, and return
  to the top. Follow the feedback below the preview and try calibration after
  changing the camera position. Your knees and ankles can stay out of frame.
- **The app won't start or says Tracker offline.** Close and reopen it. Desktop
  logs are in `%APPDATA%\RepBuddy\desktop.log` and
  `%APPDATA%\RepBuddy\postgres.log`. Keep a backup before changing database files.
- **History is empty after switching from development.** The installed app has
  its own database. It doesn't import the development database configured in `.env`.

Tracking depends on lighting, camera angle, and how much of your body is visible.
This version supports push-ups from the front view. It checks your arms and
torso, so it can't confirm that your legs are straight.

## How it works

OpenCV reads the webcam frames, and MediaPipe estimates body landmarks. The
tracker uses the estimated 3D positions to calculate elbow angles and check
whether your torso is in a plank position facing the camera.

A rep follows an **up → down → up** sequence. With default settings, both elbow
angles must reach at least 160° at the top and at most 90° at the bottom.
Each endpoint needs at least 0.12 seconds of supporting frames. Small angle
fluctuations have a four-degree margin after an endpoint begins confirming.
The plank check also has to pass before the tracker advances to the next stage.

If tracking is uncertain, the app holds your progress for up to half a second.
It won't count anything during that gap. A clearly incorrect posture clears
the unfinished rep immediately, and a longer tracking gap does the same.
After recovery, the next endpoint must be confirmed again. Missing frames
cannot supply the time needed to confirm a position.

Feedback now identifies missing shoulders, elbows, hands, or hips, unclear body
measurements, and failed posture checks. These messages describe the model's
estimate, not a guarantee about exercise form.

FastAPI connects the tracker to the interface. A WebSocket carries workout
commands and status updates, and an MJPEG stream supplies the camera preview.
In the desktop app, Python serves both the built interface and API on a local
port. Electron starts and stops Python and adds a private session token to its
requests. During browser development, Vite forwards `/api` requests to Python
on port 8000. Camera frames are processed locally and aren't stored.

## Project layout

| File | What it does |
| --- | --- |
| `desktop/main.cjs` | Opens the desktop window and manages the Python process |
| `desktop/build_backend.py` | Bundles Python, the model, frontend, and PostgreSQL |
| `desktop/electron-builder.cjs` | Windows installer settings |
| `backend/desktop.py` | Serves the packaged app and checks desktop requests |
| `backend/desktop_database.py` | Creates, starts, and stops the private database |
| `backend/tracker.py` | Plank checks, rep counting, goals, and timing |
| `backend/vision.py` | MediaPipe processing and camera overlays |
| `backend/camera.py` | Camera worker and frame handling |
| `backend/workout.py` | Workout settings, set progress, and rest timing |
| `backend/api.py` | FastAPI routes, WebSocket connection, and video stream |
| `backend/devices.py` | Webcam names and matching OpenCV device indices |
| `backend/history.py` | PostgreSQL queries, validation, and migrations |
| `backend/migrations/` | Versioned database schema changes |
| `backend/replay.py` | Replay local clips and saved tracking data to check counting |
| `compose.yaml` | Optional Docker PostgreSQL service and persistent storage |
| `frontend/src/App.tsx` | Workout interface |
| `frontend/src/useTracker.ts` | Connection to the backend and live status updates |
| `frontend/src/CameraPicker.tsx` | Webcam selection |
| `frontend/src/WorkoutHistory.tsx` | Saved sets and workout totals |
| `frontend/src/trackingFeedback.ts` | Plain language tracking and calibration guidance |
| `main.py` | Original standalone prototype, separate from the current app |

## Development

These instructions are for editing and running the source code on Windows
using PowerShell. If you installed the desktop app, you can skip this section.
The [code guide](docs/CODE_GUIDE.md) explains the project's settings and data files.

You'll need Python 3.11, Node.js 22.12 or newer, and PostgreSQL 18. Docker is
optional. Open a terminal in the project root, the folder containing this README
and `package.json`. Create a virtual environment if you don't have one, then
install the dependencies:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm ci
npm --prefix frontend ci
```

### Set up the development database

Install PostgreSQL 18 using the installer linked on the
[PostgreSQL Windows download page](https://www.postgresql.org/download/windows/).
Keep port **5432** and remember the password for the `postgres` administrator.
PostgreSQL runs as a Windows service.

Open **SQL Shell (psql)** from the Start menu. Connect to `localhost`, database
`postgres`, port `5432`, user `postgres`, using your installer password. Create
an account and database, replacing `choose_a_password` with your own password:

```sql
CREATE USER repbuddy WITH PASSWORD 'choose_a_password';
CREATE DATABASE repbuddy OWNER repbuddy;
```

Copy `.env.example` to `.env` if you don't already have one, then set:

```dotenv
DATABASE_URL=postgresql://repbuddy:choose_a_password@127.0.0.1:5432/repbuddy
```

Use your actual password and URL-encode special characters such as `@` or `#`.
`.env` stays out of Git. An existing PostgreSQL server can be used instead.

### Run in the browser

From the project root:

```powershell
npm run dev
```

This checks the database, applies migrations, and starts Python and React
together. Open [localhost:5173](http://127.0.0.1:5173). You don't need to activate
the virtual environment or run `main.py`.

Press **Ctrl+C** to stop both servers. PostgreSQL keeps running as a Windows
service, and saved sets stay in the database. If one server exits, the other
stops too.

To run either part separately for debugging, use `npm run dev:backend` or
`npm run dev:frontend` from the project root. PostgreSQL must already be running
when you start the backend on its own.

If startup reports a database error, check the PostgreSQL service in Windows
**Services** and the connection details in `.env`. Use `npm run db:migrate`
to reapply pending migrations. For **Tracker offline**, check the tracker output
in the terminal. If a port is already in use, stop older development servers.

### Optional Docker database

Instead of a native PostgreSQL service, you can use Docker Desktop with Linux
containers. Copy `.env.example` to `.env` if needed and set:

```dotenv
DATABASE_URL=postgresql://repbuddy:repbuddy_local@127.0.0.1:5433/repbuddy
```

Keep Docker Desktop running, then start the app with:

```powershell
npm run dev:docker
```

This starts the Docker database before Python and React. The first run downloads
the PostgreSQL image. After stopping the app, `npm run db:stop` stops this
database without deleting saved sets. It doesn't stop a native PostgreSQL service.
The Docker credentials are for local development, and port 5433 is local only.

`npm run dev` never launches Docker. If `DATABASE_URL` is unset, the backend
defaults to the Docker connection on port 5433, so set `.env` when using native
PostgreSQL. Changing the URL selects a different database; it doesn't move history.

### Build the desktop app

Use Windows with Python 3.11, Node.js 22.12 or newer, and PostgreSQL 18 installed.
Create the virtual environment and install the Node dependencies shown at the
start of [Development](#development), then run:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
npm run desktop:build
npm run desktop:smoke
```

The build copies PostgreSQL from `C:\Program Files\PostgreSQL\18`. Set
`REPBUDDY_POSTGRES_HOME` to its program folder if yours is elsewhere.
You don't need to create a development database or start the PostgreSQL service
to build the installer.

The installer is written to `release\RepBuddy-Setup-0.1.0-x64.exe`. Share that
file when distributing the app. The executable in `release\win-unpacked` needs
the other files in that folder to run.

The smoke check opens the packaged app with temporary data, checks the model,
interface, connection, and shutdown, and leaves logs and a screenshot under
`build\packaged-smoke-*`. It doesn't use the webcam or install the app.

For testing the Electron shell from source, run `npm run desktop:prepare`, then
`npm run desktop:start`. Run the prepare step again after changing Python or
frontend code. See [desktop setup and builds](docs/DESKTOP.md) for more details.

### Tests

To run the Python tests and check the frontend:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
npm --prefix frontend run build
npm --prefix frontend run lint
npm --prefix frontend test
```

The Python tests cover startup, rep logic, calibration, countdowns, camera
selection, saving, and the API using synthetic poses and fake cameras. Frontend
tests check status, guidance, controls, and history response handling.

Use the [tracking test guide](docs/TRACKING_TESTS.md) to replay a recorded video,
export its landmarks, and compare the counter with manually labelled reps.
The included traces test counting rules with synthetic data. Accuracy on real
push-ups still needs measured recordings with different people and camera setups.

PostgreSQL integration tests require a separate test database. In SQL Shell,
connect as `postgres` and create it once:

```sql
CREATE DATABASE repbuddy_test OWNER repbuddy;
```

Then run the tests from PowerShell, using your RepBuddy database password:

```powershell
$env:TEST_DATABASE_URL = 'postgresql://repbuddy:choose_a_password@127.0.0.1:5432/repbuddy_test'
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

These tests create and remove their own schema. They check persistence,
duplicate saves, pagination, summaries, and migrations against real PostgreSQL.
For Docker, create the test database with
`docker compose exec -T db createdb -U repbuddy repbuddy_test`, then use port
5433 and password `repbuddy_local` in `TEST_DATABASE_URL`.
