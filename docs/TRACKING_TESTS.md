# Checking tracking reliability

Use recorded push ups to compare changes without repeating the same workout.
The replay tool reads a local video or a saved JSON trace. It does not open a
webcam, connect to the database, or save a workout in your history.

The included recordings are synthetic traces. Their angles and body points are
made up to test the counting rules. Passing these tests does not show how well
the tracker works on real people. No real video accuracy results are included.

## Start with the included examples

Run these commands from the project folder.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_replay.py -v
.\.venv\Scripts\python.exe -m backend.replay tests/fixtures/tracking/stable_rep.json --expected-reps 1
```

The fixtures cover a complete rep, a brief angle spike, a short tracking loss,
a longer tracking loss, and a clearly incorrect posture. The tests also check
saved body points, invalid files, video frame rates, and manual rep labels.

## Check a real recording

Record a front facing view with both shoulders, elbows, wrists, and hips visible.
Use a video with a constant frame rate. The tool uses the recorded frame rate
and frame number to calculate time, rather than the speed of your computer.
Convert variable frame rate videos before testing them.

Count the full reps by watching the video yourself, then run the tool with that
total. Replace the example path and total with your own recording.

```powershell
.\.venv\Scripts\python.exe -m backend.replay "C:\Videos\pushups.mp4" --expected-reps 8 --export "C:\Videos\pushups.trace.json"
```

The exported trace includes timestamps, elbow angles, tracking results, and the
body points estimated by MediaPipe. Those points can be checked again after
changing the posture rules, without running the video through MediaPipe again.
Keep recordings and traces local unless everyone recorded agrees to share them.

Replay the saved trace with the same command.

```powershell
.\.venv\Scripts\python.exe -m backend.replay "C:\Videos\pushups.trace.json" --expected-reps 8
```

Replay uses the default angle thresholds and the normal hold and tracking loss
rules. It does not load a live camera calibration or run the countdown.

## Measure missed reps and extra reps

A total only gives the difference between the detected count and the real count.
One missed rep and one extra rep could cancel out, so an equal total does not
prove that every rep was counted correctly.

For a more useful check, write down the time when each real rep finishes at the
top position. Save the times in seconds in a JSON file. For example, a recording
with three real reps might have these labels.

```json
[2.1, 4.8, 7.3]
```

Then provide the labels instead of a total.

```powershell
.\.venv\Scripts\python.exe -m backend.replay "C:\Videos\pushups.mp4" --expected-times "C:\Videos\pushups.labels.json" --tolerance 0.5
```

Each detected completion can match one manual label within the chosen tolerance.
The default tolerance is half a second. Use the same tolerance when comparing
versions. Missing matches are missed reps, and detections without a match are
extra reps. Labels must be in increasing order and inside the recording timeline.

## Read the report

| Field | Meaning |
| --- | --- |
| `countedReps` | Full reps counted by the tracker. |
| `completionTimestamps` | Times when those reps were counted. |
| `countDifference` | Detected total minus the manually counted total. |
| `completionMatches` | Matched, missed, and extra reps when timed labels are supplied. |
| `trackingLossSeconds` | Time spent with uncertain tracking. |
| `trackingLossRate` | Fraction of the recording with uncertain tracking. |
| `invalidPostureSeconds` | Time spent in clearly incorrect posture. |
| `processingFps` | Number of frames processed per second on this computer. |
| `processingMode` | Whether timing covers video pose processing or a saved trace. |
| `landmarkFrames` | Frames checked again using saved body points. |
| `cachedMeasurementFrames` | Frames that only contain saved angles and tracking results. |

Each tracking state lasts until the next frame. The final frame has no measured
interval after it. A single frame trace therefore has zero measured duration.
Video processing speed includes MediaPipe. Saved trace speed does not, so compare
speed only between runs using the same processing mode.

## Build a useful set of recordings

Include normal reps, faster reps, slower reps, pauses, shallow movements, hidden
hands, and standing elbow bends. Also try different lighting and camera heights.
Include recordings with no valid push ups to check for extra counts.

Keep the same videos and manual labels when comparing changes. Watch clips with
unexpected results and save their traces as regression cases. Record missed reps,
extra reps, tracking loss, and processing speed before and after a change.

## Trace files

Trace version 1 stores a source description and a list of frames. Every frame
has an increasing timestamp, both elbow angles, pose and plank flags, a tracking
quality, and an optional reason. Missing angles are JSON null. Nonfinite numbers
and repeated or reversed timestamps are rejected.

Optional image and world landmarks each contain all 33 body points. Every point
has x, y, and z coordinates. Image points should also include visibility scores.
When body points are present, replay recalculates elbow angles and posture from
those points. Otherwise it uses the saved measurements. The synthetic fixtures
show the smaller format used to test counting alone.
