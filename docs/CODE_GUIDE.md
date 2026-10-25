Reading the project settings.

The package files list the commands and libraries used by the app. The root
package starts Python and React together for development and builds the desktop
installer. Electron starts the packaged Python program when the desktop app
opens. The frontend package builds and checks the browser interface.
Lock files record the exact library versions
installed by npm. These files use JSON, which does not allow comments.

The TypeScript settings check types and control how the frontend code is
compiled. The root TypeScript file points to separate settings for the browser
app and its development tools.

The tracking fixture files contain sample frames used by automated tests.
Each frame has a time, elbow angles, and a tracking quality result. Some traces
also contain body landmarks so the pose checks can be run again. These files
use JSON too.

The first database migration creates the workouts table. The identifier makes
each finished set unique. The completion date includes its timezone. The rep
count must match an allowed goal. The duration must be finite and cannot be
negative. The index helps PostgreSQL load the newest workouts quickly.

Applied migrations have saved file fingerprints. Changing even a comment in
an applied file would fail the startup check. The existing migration is
explained here so its original file remains valid.

Python comments explain the camera loop, rep decisions, calibration, API
requests, database operations, and tests. Frontend comments explain the React
components, stored screen state, live updates, styles, and input checks.
