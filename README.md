# RepBuddy

RepBuddy counts push-ups using your webcam. Face the camera, choose a rep goal,
and follow your progress with a live preview, rep counter, and session timer.

Python handles the camera and pose tracking, while React and TypeScript handle
the interface. Everything runs locally on your computer.

See the [changelog](CHANGELOG.md) for recent updates and what's planned next.

## Getting started

The instructions below are for Windows PowerShell. You'll need Python 3.11,
Node.js 22.12 or newer, a webcam, and PostgreSQL. Docker is optional.

### Set up PostgreSQL once

Install PostgreSQL 18 using the installer linked on the
[PostgreSQL Windows download page](https://www.postgresql.org/download/windows/).
Keep port **5432** and remember the password you choose for the `postgres`
administrator account. The installer sets up a Windows service that starts
PostgreSQL automatically with Windows.

Open **SQL Shell (psql)** from the Start menu. Connect to `localhost`, database
`postgres`, port `5432`, user `postgres`, using your installer password. Create
an account and database for RepBuddy, replacing `choose_a_password` below:

```sql
CREATE USER repbuddy WITH PASSWORD 'choose_a_password';
CREATE DATABASE repbuddy OWNER repbuddy;
```

In the project folder, copy `.env.example` to `.env` if you don't already have
one. Set the connection to the account and database you just created:

```dotenv
DATABASE_URL=postgresql://repbuddy:choose_a_password@127.0.0.1:5432/repbuddy
```

Use your actual password. URL-encode any special characters in the password,
such as `@` or `#`. `.env` stays out of Git. If you already have a PostgreSQL
server, you can use its connection URL instead.

### Start the app

Open a terminal in the `RepBuddy` project folder. If you don't already have a
`.venv` folder, create one:

```powershell
py -3.11 -m venv .venv
```

Install the dependencies once:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm install
npm --prefix frontend install
```

Then start the app:

```powershell
npm run dev
```

This connects to PostgreSQL, applies database migrations, then runs Python and
React together in the same terminal. Open
[localhost:5173](http://127.0.0.1:5173) to use the app. You don't need to activate
the virtual environment or run `main.py`.

Press **Ctrl+C** in the terminal to stop Python and React. If one server exits,
the other stops too. PostgreSQL keeps running as a Windows service, so you
don't need to open a separate program each time. Saved workouts stay in the
database between app restarts.

### Optional: use Docker for PostgreSQL

If you prefer Docker, keep Docker Desktop running with Linux containers and
set this connection in `.env`:

```dotenv
DATABASE_URL=postgresql://repbuddy:repbuddy_local@127.0.0.1:5433/repbuddy
```

Then run:

```powershell
npm run dev:docker
```

This starts the bundled PostgreSQL service before launching the app. The first
run downloads the PostgreSQL image. `npm run db:stop` stops this Docker database
without deleting saved workouts; it does not stop a native PostgreSQL service.
The Docker database is available only on this computer at port 5433, and its
credentials are for local development.

`npm run dev` never launches Docker. If `DATABASE_URL` is unset, the app still
uses the previous Docker connection on port 5433 for compatibility, so set
`.env` when using native PostgreSQL. Changing the connection selects a
different database; it doesn't move existing workout history between them.

## Using the tracker

1. Choose your webcam from the **Camera** menu. Use **Refresh** after plugging
   in a camera, and stop the current camera before switching devices.
2. Place your camera in front of you and keep it roughly level.
3. Make sure your shoulders, elbows, wrists, and hips stay visible throughout
   the movement. Your knees and ankles can be out of frame.
4. Choose a goal of 5, 10, 15, or 20 reps, then press **Start**. The preview
   opens with a five-second countdown. The timer and rep counter start after
   it ends; **Cancel countdown** keeps the preview on without starting the set.
5. Get into a plank with your arms extended. Lower yourself, then push back up
   to complete a rep.

The preview shows your tracked joints and elbow angles. The status below it
lets you know when the tracker needs you to adjust your position.

- **Pause** stops counting and pauses the timer, but keeps the camera on.
- **Resume** gives you another five-second countdown before continuing the set.
  Start with your arms extended again.
- **Stop camera** turns off the webcam and keeps your rep count and time.
- **Reset** clears the set and turns off the camera. Use it before changing
  your goal.

Reaching your goal pauses the set and saves it to PostgreSQL. Press **New set**
when you're ready to go again. Closing the last connected app tab also releases
the webcam.

## Workout history

The history panel shows completed sets with their date, reps, goal, and active
time. It also shows total sets, total reps, your best set, and this week's reps.
Dates use your local time; weekly totals run from Monday to Sunday in UTC.
Use **Load older sets** to see more records.

Only sets that reach their goal are saved. Pausing, stopping the camera, or
resetting an unfinished set doesn't create a history entry. Countdown time
isn't included in the saved duration. Camera images aren't stored.

If a save fails, keep the app open and press **Retry saving set** once PostgreSQL
is available again. Starting a new set and resetting are disabled until that
save succeeds. Retrying or reconnecting won't duplicate an already saved set.

## How it works

OpenCV reads the webcam frames, and MediaPipe estimates body landmarks. The
tracker uses the estimated 3D positions to calculate elbow angles and check
whether your torso is in a plank position facing the camera.

A rep follows an **up → down → up** sequence. Both elbow angles must be above
160° for the up position and below 90° for the down position. The plank check
also has to pass before the tracker advances to the next stage.

If tracking briefly drops out, the app holds your progress for up to half a
second. It won't count anything during that gap. A longer gap clears the
unfinished rep, so you'll need to return to the up position.

FastAPI connects the tracker to the interface. A WebSocket carries workout
commands and status updates, and an MJPEG stream supplies the camera preview.
Vite forwards `/api` requests to the Python server on port 8000. The camera is
processed locally and only opens when you press **Start**.

## Project layout

| File | What it does |
| --- | --- |
| `backend/tracker.py` | Plank checks, rep counting, goals, and timing |
| `backend/vision.py` | MediaPipe processing and camera overlays |
| `backend/camera.py` | Camera worker and frame handling |
| `backend/api.py` | FastAPI routes, WebSocket connection, and video stream |
| `backend/devices.py` | Webcam names and matching OpenCV device indices |
| `backend/history.py` | PostgreSQL queries, validation, and migrations |
| `backend/migrations/` | Versioned database schema changes |
| `compose.yaml` | Optional Docker PostgreSQL service and persistent storage |
| `frontend/src/App.tsx` | Workout interface |
| `frontend/src/useTracker.ts` | Connection to the backend and live status updates |
| `frontend/src/CameraPicker.tsx` | Webcam selection |
| `frontend/src/WorkoutHistory.tsx` | Saved sets and workout totals |
| `main.py` | Original standalone prototype, separate from the current app |

## A few things to keep in mind

Tracking depends on your lighting, camera angle, and how much of your body is
visible. The plank check uses your arms and torso, so it can't confirm that
your legs are straight. This version supports push-ups from the front view.

If the camera won't open, close other apps using it and check your Windows
camera permissions. If you see **Tracker offline**, check the `tracker` output
in the terminal. The interface reconnects automatically when the backend is
available.

If a port is already in use, stop any older copies of the app before starting
it again. Run `npm run dev` from the project root: running it inside `frontend`
starts only the interface.

If startup reports a database error, check that your PostgreSQL service is
running in the Windows **Services** app and that `DATABASE_URL` in `.env`
matches your database, port, user, and password. For the Docker option, check
Docker Desktop and use `npm run dev:docker`. You can reapply pending migrations
with `npm run db:migrate`.

## Development

To run either part separately for debugging, use `npm run dev:backend` or
`npm run dev:frontend` from the project root. PostgreSQL must already be running
when you start the backend on its own.

To run the Python tests and check the frontend:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
npm --prefix frontend run build
npm --prefix frontend run lint
npm --prefix frontend test
```

The Python tests cover startup, rep logic, countdowns, camera selection,
saving, and the API using synthetic poses and fake cameras. Frontend tests
check status and history response handling. Checking actual push-up recognition
still needs a live camera test.

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
