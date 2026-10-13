# Changelog

Updates to RepBuddy, with the newest changes first. Future tasks are listed at
the bottom. Dates for earlier updates come from the Git history.

## Unreleased

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

- [ ] Package the React interface and Python tracker as a desktop app.
- [ ] Test with more camera positions and lighting conditions, then adjust
  tracking to reduce missed reps.
- [ ] Investigate the API test that stalled during local testing.
- [ ] Decide whether to keep or remove the original `main.py` prototype.
- [ ] Add screenshots and a short workout demo to the README.
