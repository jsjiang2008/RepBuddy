# Changelog

Updates to RepBuddy, with the newest changes first. Future tasks are listed at
the bottom. Dates for earlier updates come from the Git history.

## 2026-10-14 — Small improvements, no more Docker

- Made Docker optional. `npm run dev` uses the configured PostgreSQL server;
  `npm run dev:docker` starts the bundled Docker database when requested.
- Added setup instructions for PostgreSQL running as a Windows service and
  tests for startup with and without Docker.

## 2026-10-13 — PostgreSQL integration (workout history, highscores, weekly totals, etc.)

- Added webcam selection with device names and a refresh option.
- Added a five-second countdown with a live preview before starting or resuming
  a set. Cancelling it leaves the timer and rep counter paused.
- Added PostgreSQL workout history with automatic saves for goal-completed
  sets, pagination, weekly rep totals, and a best-set record.
- Added save status and retries so a database interruption doesn't silently
  discard a completed set or create duplicate history entries on retry.
- Added a local PostgreSQL Docker service, persistent storage, and versioned
  migrations. `npm run dev` prepares the database before starting the app.
- Added tests for camera selection, countdowns, save retries, PostgreSQL
  persistence, and frontend response handling.

## 2026-10-12 — Startup, type fixes, and documentation

- Added `npm run dev` at the project root to start Python and React together.
  Ctrl+C stops both servers, and either server exiting stops the other.
- Updated the MediaPipe import and Python type annotations for pose results
  and OpenCV frames.
- Fixed type-checking errors in the API and camera tests.
- Rewrote the README with setup instructions, controls, tracking details, and
  troubleshooting tips.
- Added this changelog to keep track of completed work and next steps.

## 2026-09-29 — React interface and Python backend

- Built the interface with React, TypeScript, and Vite.
- Added a live camera preview with pose overlays, a rep counter, a timer,
  and set progress.
- Added rep goals of 5, 10, 15, or 20, along with Start, Pause, Resume, Reset,
  and Stop camera controls.
- Connected the interface to Python through FastAPI. WebSockets carry commands
  and tracking updates; an MJPEG stream provides the video preview.
- Split the Python backend into tracking, pose processing, camera, and API
  modules.
- Added automatic reconnection, tracking status messages, and camera error
  handling.
- Made the camera open on Start and release on Stop, Reset, or when the last
  connected app tab closes.
- Added tests for rep counting, camera handling, and the API.
- Updated dependencies and the root `.gitignore` for the Python and React code.

## 2026-09-25 — Front-facing tracking

- Added a plank check so elbow movement alone doesn't count as a push-up.
- Switched to front-facing tracking using MediaPipe's estimated 3D landmarks.
- Removed the need to see knees and ankles during a rep.
- Required a complete up → down → up movement before adding to the counter.
- Added a 0.5-second grace period so brief tracking loss doesn't immediately
  clear an unfinished rep. Invalid frames don't count toward a rep.

## 2026-09-19 — First working counter

- Added the original elbow-angle counter and a basic workout display.
- Drew custom landmarks and connections over the camera feed.
- Added a fullscreen view that preserves the camera's aspect ratio.

## To do

Suggested order for the next updates. Completed tasks are checked off below.

### First: make tracking more reliable

- [ ] **Measure counting accuracy.** Test full sets with different lighting,
  camera heights, and brief tracking loss. Compare the actual reps with the
  counter, record missed and extra reps, and use those results to tune the
  tracker. Save example landmark sequences as regression tests.
- [x] **Investigate the stalled API test.** The restricted test environment
  blocked Python's event-loop socket setup. API tests pass outside that
  environment, including camera cleanup on disconnect.
- [ ] **Automate the checks.** Add frontend tests for workout controls and
  connection loss. Run them alongside the Python tests, frontend build, and
  lint checks in [GitHub Actions](https://docs.github.com/en/actions/tutorials/build-and-test-code/python)
  on pushes and pull requests.

### Next: improve the workout experience

- [ ] **Explain why a rep didn't count.** Show specific feedback when arms or
  hips aren't visible, the torso check fails, or the movement doesn't reach
  the required elbow angles. Base each message on what the tracker can
  actually detect.
- [x] **Add camera selection and a countdown.** Let users choose a webcam,
  preview their position, and get ready during a short countdown before the
  timer and counting start.
- [x] **Save workout history.** Store each completed set's date, reps, goal,
  and duration in a local [PostgreSQL](https://www.postgresql.org/about/)
  database, accessed through the Python backend. Add schema migrations,
  document database setup, and check the database connection during startup.
  Add a history screen with weekly rep totals and a best-set record. Check
  that records survive restarting the app and aren't duplicated on reconnect.

### Then: package it and show it working

- [ ] **Create a desktop installer.** Use
  [Electron](https://www.electronjs.org/docs/latest/tutorial/application-distribution)
  for the React interface and bundle the Python tracker and its dependencies.
  Include local PostgreSQL setup and persistent data storage in the install
  process. Launch and stop the backend with the app, then test the installer
  on a Windows machine without Python, Node.js, or PostgreSQL preinstalled.
- [ ] **Add a project demo.** Include screenshots, a short video of a full
  workout, and an architecture diagram in the README. Add measured tracking
  results and describe the test setup so the numbers have context.
- [ ] **Clean up the old prototype.** Decide whether to keep or remove
  `main.py`, and make the main app's entry points clear.
