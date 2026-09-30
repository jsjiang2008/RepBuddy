# RepBuddy

Front-facing push-up tracking with a React/TypeScript interface and a local
Python camera worker. Frames stay on this computer. The frontend now uses real
tracking results, not a simulated timer.

## Run locally (Windows PowerShell)

Use Python 3.11 for the pinned MediaPipe release and a current Node.js LTS.
From the RepBuddy project root, install dependencies once:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm --prefix frontend install
```

If you do not have a virtual environment yet, create it with
`py -3.11 -m venv .venv` first.

Start Python in one terminal, from the project root:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.api:app --host 127.0.0.1 --port 8000
```

Start React in a second terminal, also from the root:

```powershell
npm --prefix frontend run dev
```

Open http://127.0.0.1:5173. Restart Vite if it was running before the proxy
configuration was added. Run one Python server process (no extra workers).

## Workout controls

- **Start / Resume:** opens the camera if needed and begins counting. A new
  up → down → up cycle is required after resuming.
- **Pause:** freezes counting and active time; the camera preview stays on.
- **Stop camera:** releases the webcam, preserving completed reps and time.
- **Reset:** releases the camera and clears the current set; then you can
  change the goal (5, 10, 15, or 20 reps).
- Reaching the goal pauses counting. **New set** starts from zero.
- Closing the last connected frontend stops the camera. Reconnecting never
  automatically starts it.

Keep the camera approximately level, facing you, with arms and hips visible.
Knees and ankles are not required. The original 0.5-second tracking grace period
is preserved. Without leg landmarks this checks torso posture, not full leg form.

If the webcam will not open, close other camera applications (including the
standalone tracker), check Windows camera permissions, and press Start again.
If the page says **Tracker offline**, check the Python terminal and port 8000.
The frontend reconnects automatically.

## Code layout

- `backend/tracker.py`: pose geometry, rep state, elapsed time, grace period.
- `backend/vision.py`: MediaPipe processing and landmark overlays.
- `backend/camera.py`: one worker thread owns the camera and pose model.
- `backend/api.py`: WebSocket commands/status and MJPEG preview.
- `frontend/src/useTracker.ts`: typed status, command acknowledgments, reconnects.
- `frontend/src/App.tsx`: workout screen using backend state.
- `main.py`: optional standalone OpenCV window using the same tracker.

No camera or GUI starts merely by importing a Python module. Start commands
create the worker; HTTP video clients only read the latest encoded frame.

Vite proxies `/api` to Python at `127.0.0.1:8000`, so React connects to the same
origin. `/api/ws` sends status about ten times per second and accepts commands:

```json
{"command": "start", "requestId": 1}
```

Other commands: `pause`, `stop`, `reset`, and `goal` (with a `goal` integer).
Status messages contain reps, goal, stage, elapsedSeconds, running, completed,
hasPose, inPlank, inGracePeriod, cameraState, error, commandError, and ackId.
`/api/video` streams JPEG frames; `/api/health` checks server availability.

The API is for local development. Electron packaging is not included yet.

## Validation

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
npm --prefix frontend run build
npm --prefix frontend run lint
```

Automated tests use synthetic poses and a fake camera. Actual rep recognition
also needs a live workout test under your lighting and camera placement.
