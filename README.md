# RepBuddy

RepBuddy counts push-ups using your webcam. Face the camera, choose a rep goal,
and follow your progress with a live preview, rep counter, and session timer.

Python handles the camera and pose tracking, while React and TypeScript handle
the interface. Everything runs locally on your computer.

See the [changelog](CHANGELOG.md) for recent updates and what's planned next.

## Getting started

The instructions below are for Windows PowerShell. You'll need Python 3.11,
Node.js 22.12 or newer, and a webcam.

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

This runs Python and React together in the same terminal. Open
[localhost:5173](http://127.0.0.1:5173) to use the app. You don't need to activate
the virtual environment or run `main.py`.

Press **Ctrl+C** in the terminal to stop both servers. If one server exits, the
other stops too.

## Using the tracker

1. Place your camera in front of you and keep it roughly level.
2. Make sure your shoulders, elbows, wrists, and hips stay visible throughout
   the movement. Your knees and ankles can be out of frame.
3. Choose a goal of 5, 10, 15, or 20 reps, then press **Start**.
4. Get into a plank with your arms extended. Lower yourself, then push back up
   to complete a rep.

The preview shows your tracked joints and elbow angles. The status below it
lets you know when the tracker needs you to adjust your position.

- **Pause** stops counting and pauses the timer, but keeps the camera on.
- **Resume** continues the set. Start with your arms extended again.
- **Stop camera** turns off the webcam and keeps your rep count and time.
- **Reset** clears the set and turns off the camera. Use it before changing
  your goal.

Reaching your goal pauses the set. Press **New set** when you're ready to go
again. Closing the last connected app tab also releases the webcam.

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
| `frontend/src/App.tsx` | Workout interface |
| `frontend/src/useTracker.ts` | Connection to the backend and live status updates |
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

## Development

To run either part separately for debugging, use `npm run dev:backend` or
`npm run dev:frontend` from the project root.

To run the Python tests and check the frontend:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
npm --prefix frontend run build
npm --prefix frontend run lint
```

The tests cover the rep logic, camera lifecycle, and API using synthetic poses
and a fake camera. Checking how well it recognizes actual push-ups still needs
a live camera test.
