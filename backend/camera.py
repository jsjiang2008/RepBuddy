"""Read one camera in the background and share its latest preview with the app."""
import logging
import math
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from uuid import uuid4

from .devices import list_video_devices, open_video_capture
from .tracker import PushUpTracker
from .workout import WorkoutPlan

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _CompletedSet:
    """Keep the finished result unchanged while the database saves it."""
    id: str
    completedAt: str
    reps: int
    goal: int
    durationSeconds: float


class CameraService:
    """Manage the camera, workout controls, countdown, and background saves."""
    def __init__(self, camera_index=0, capture_factory=None, processor_factory=None,
                 device_provider=None, clock=time.monotonic, countdown_seconds=5,
                 on_completed=None):
        # Optional replacements let tests run without a real camera or clock.
        self.clock = clock
        self.tracker = PushUpTracker(clock=clock)
        self.workout = WorkoutPlan()
        self.camera_index = camera_index
        self.capture_factory = capture_factory
        self.processor_factory = processor_factory
        self.device_provider = device_provider or list_video_devices
        self.countdown_seconds = countdown_seconds
        self.countdown_deadline = None
        self.start_requested = False
        self.on_completed = on_completed
        self.completed_record = None
        self.history_state = None
        self.history_error = None
        self.history_version = 0
        self.history_thread = None
        # Locks stop controls and camera updates from changing the same state at once.
        self.lock = threading.RLock()
        self.control_lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread = None
        self.camera_state = 'off'
        self.error = None
        self.jpeg = None
        self.frame_id = 0

    def snapshot(self):
        # Copy the current state into a message the frontend can display.
        with self.lock:
            countdown = (max(0, math.ceil(self.countdown_deadline - self.clock()))
                         if self.countdown_deadline is not None else 0)
            tracker_status = self.tracker.snapshot()
            return {**tracker_status, **self.workout.snapshot(self.clock(), tracker_status['elapsedSeconds']),
                    'cameraState': self.camera_state,
                    'error': self.error, 'cameraIndex': self.camera_index,
                    'countdownSeconds': countdown, 'historyState': self.history_state,
                    'historyError': self.history_error,
                    'historyVersion': self.history_version}

    def latest_frame(self):
        # The frame number tells the video stream whether the image changed.
        with self.lock:
            return self.frame_id, self.jpeg

    def list_cameras(self):
        # Keep device discovery separate from a camera that may be opening or closing.
        with self.control_lock:
            cameras = self._available_cameras()
            with self.lock:
                return {'cameras': cameras, 'selectedIndex': self.camera_index}

    def _available_cameras(self):
        # Replace driver failures with a useful message for the user.
        try:
            return self.device_provider()
        except Exception:
            logger.exception('Could not list cameras')
            raise RuntimeError('Could not list cameras. Reconnect your webcam and try again.') from None

    def _require_saved(self):
        # Protect a completed set from being cleared before its save succeeds.
        if self.history_state == 'saving':
            raise ValueError('Wait for your completed set to finish saving.')
        if self.history_state == 'error':
            raise ValueError('Retry saving your completed set before starting or resetting.')

    def _clear_completed_set(self):
        # Clear the saved result notice when a new set begins.
        self.completed_record = None
        self.history_state = None
        self.history_error = None

    def _cancel_countdown(self):
        # Clear both a queued countdown and one that has already started.
        self.start_requested = False
        self.countdown_deadline = None

    def _require_fresh_set(self):
        # Calibration must not change the rules during an unfinished set.
        self._require_saved()
        if self.workout.state not in ('idle', 'complete'):
            raise ValueError('Reset the workout before calibrating.')
        if (self.tracker.running or self.start_requested or
                self.countdown_deadline is not None):
            raise ValueError('Pause the workout before calibrating.')
        if (self.tracker.counter < self.tracker.goal and
                (self.tracker.counter > 0 or self.tracker.elapsed > 0)):
            raise ValueError('Reset the current set before calibrating.')

    def _ensure_camera_worker(self):
        """Open one background camera reader while the caller holds the state lock."""
        if self.thread is not None and self.thread.is_alive():
            if self.stop_event.is_set():
                raise ValueError('The camera is stopping. Try again in a moment.')
            return
        self.error = None
        self.jpeg = None
        self.camera_state = 'starting'
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run, daemon=True,
                                       name='repbuddy-camera')
        self.thread.start()

    def command(self, command, goal=None, camera_index=None, *, sets=None, rest_seconds=None):
        # Process one control at a time while still allowing live images and status updates.
        with self.control_lock:
            if command == 'camera':
                if type(camera_index) is not int or camera_index < 0:
                    raise ValueError('Choose an available camera.')
                with self.lock:
                    if self.camera_state != 'off':
                        raise ValueError('Stop the camera before choosing another one.')
                cameras = self._available_cameras()
                if not any(camera['index'] == camera_index for camera in cameras):
                    raise ValueError('That camera is no longer available. Refresh the camera list.')
                with self.lock:
                    if self.camera_index != camera_index:
                        self.tracker.clear_calibration()
                    self.camera_index = camera_index
                    self.error = None
                return
            if command == 'retrySave':
                with self.lock:
                    if self.history_state == 'saving':
                        return
                    if self.history_state != 'error' or self.completed_record is None:
                        raise ValueError('There is no completed set waiting to be saved.')
                    record = self.completed_record
                    self.history_state = 'saving'
                    self.history_error = None
                self._start_save(record)
                return
            if command in ('calibrate', 'cancelCalibration', 'clearCalibration'):
                with self.lock:
                    if command == 'cancelCalibration':
                        self.tracker.cancel_calibration()
                        return
                    self._require_fresh_set()
                    if command == 'clearCalibration':
                        self.tracker.clear_calibration()
                        return
                    if self.thread is not None and self.thread.is_alive() and self.stop_event.is_set():
                        raise ValueError('The camera is stopping. Try calibrating again in a moment.')
                    if self.tracker.calibrating:
                        return
                    if self.tracker.counter >= self.tracker.goal:
                        self.tracker.reset()
                        self.workout.reset()
                        self._clear_completed_set()
                    self.tracker.begin_calibration()
                    self._ensure_camera_worker()
                return
            if command in ('stop', 'reset'):
                if command == 'reset':
                    with self.lock:
                        self._require_saved()
                        # Stop counting before another frame can complete a set.
                        self._cancel_countdown()
                        self.tracker.pause()
                        self.stop_event.set()
                self._stop()
                if command == 'reset':
                    with self.lock:
                        self.tracker.reset()
                        self.workout.reset()
                        self.error = None
                        self._clear_completed_set()
                return
            with self.lock:
                if command == 'configureWorkout':
                    self._require_saved()
                    if (self.tracker.calibrating or self.camera_state in ('starting', 'stopping') or
                            self.tracker.running or self.tracker.counter > 0 or self.tracker.elapsed > 0):
                        raise ValueError('Reset the workout before changing its settings.')
                    self.workout.configure(sets, rest_seconds)
                elif command == 'skipRest':
                    self._require_saved()
                    self.workout.skip_rest(self.clock())
                elif command == 'goal':
                    if self.workout.state != 'idle':
                        raise ValueError('Reset the workout before changing its goal.')
                    if (self.camera_state == 'starting' or self.start_requested or
                            self.countdown_deadline is not None or self.tracker.calibrating):
                        raise ValueError('Pause or reset the set before changing its goal.')
                    self.tracker.set_goal(goal)
                elif command == 'pause':
                    self.workout.pause(self.clock())
                    self._cancel_countdown()
                    self.tracker.cancel_calibration()
                    self.tracker.pause()
                    if self.camera_state == 'starting':
                        self.stop_event.set()
                elif command == 'start':
                    self._require_saved()
                    if self.tracker.calibrating:
                        raise ValueError('Finish or cancel calibration before starting the set.')
                    if self.thread is not None and self.thread.is_alive():
                        if self.stop_event.is_set():
                            raise ValueError('The camera is stopping. Try Start again in a moment.')
                        if (self.tracker.running or self.start_requested or
                                self.countdown_deadline is not None):
                            return
                    if self.workout.state == 'complete':
                        self.tracker.reset()
                        self._clear_completed_set()
                    self.workout.start(self.clock())
                    self.start_requested = self.workout.state == 'active'
                    self._ensure_camera_worker()
                else:
                    raise ValueError('Unknown workout command.')

    def _stop(self):
        # Ask the reader to exit, then wait briefly for it to release the camera.
        with self.lock:
            self.workout.pause(self.clock())
            self._cancel_countdown()
            self.tracker.cancel_calibration()
            self.tracker.pause()
            self.stop_event.set()
            thread = self.thread
            self.jpeg = None
            self.camera_state = 'stopping' if thread and thread.is_alive() else 'off'
        if thread and thread.is_alive():
            thread.join(timeout=5)
        with self.lock:
            if not thread or not thread.is_alive():
                self.camera_state = 'off'
            self.tracker.update(float('nan'), float('nan'), False, False)

    def close(self):
        """Release the webcam and allow a pending database save to finish."""
        with self.control_lock:
            self._stop()
            history_thread = self.history_thread
            if history_thread is not None and history_thread.is_alive():
                history_thread.join(timeout=5)

    def _run(self):
        capture = processor = None
        try:
            # Load camera libraries only when a preview is requested.
            import cv2
            factory = self.capture_factory or open_video_capture
            capture = factory(self.camera_index)
            if not capture.isOpened():
                raise RuntimeError('Could not open the webcam. Close other camera apps and check camera permissions.')
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            if self.processor_factory is None:
                from .vision import PoseProcessor
                processor = PoseProcessor()
            else:
                processor = self.processor_factory()
            while not self.stop_event.is_set():
                # Analyze the image and compress it for the browser preview.
                success, frame = capture.read()
                if not success:
                    raise RuntimeError('The webcam stopped sending frames. Check the camera and try Start again.')
                frame, left, right, in_plank, has_pose = processor.process(frame)
                success, encoded = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                if not success:
                    raise RuntimeError('Could not encode the camera preview.')
                record_to_save = None
                with self.lock:
                    if self.stop_event.is_set():
                        break
                    self.camera_state = 'ready'
                    # Rest ends only while the camera is ready and the last set is saved.
                    if self.workout.next_set(self.clock(), self.history_state not in ('saving', 'error')):
                        self.tracker.reset()
                        self._clear_completed_set()
                        self.start_requested = True
                    if self.start_requested:
                        # Start the countdown only after the first usable preview frame.
                        self.countdown_deadline = self.clock() + self.countdown_seconds
                        self.start_requested = False
                    if (self.countdown_deadline is not None and
                            self.clock() >= self.countdown_deadline):
                        self.countdown_deadline = None
                        self.tracker.start()
                    was_completed = self.tracker.counter >= self.tracker.goal
                    # Pass uncertainty reasons along with angles so the counter can pause safely.
                    assessment = getattr(processor, 'assessment', None)
                    self.tracker.update(left, right, in_plank, has_pose,
                                        quality=assessment.quality if assessment is not None else None,
                                        reason=assessment.reason if assessment is not None else None)
                    self.jpeg = encoded.tobytes()
                    self.frame_id += 1
                    if not was_completed and self.tracker.counter >= self.tracker.goal:
                        self.workout.finish_set(self.tracker.snapshot()['elapsedSeconds'], self.clock())
                    if (not was_completed and self.tracker.counter >= self.tracker.goal
                            and self.on_completed is not None):
                        # Capture one result when the goal is first reached.
                        record_to_save = _CompletedSet(
                            id=str(uuid4()),
                            completedAt=datetime.now(timezone.utc).isoformat(),
                            reps=self.tracker.counter, goal=self.tracker.goal,
                            durationSeconds=self.tracker.snapshot()['elapsedSeconds'],
                        )
                        self.completed_record = record_to_save
                        self.history_state = 'saving'
                        self.history_error = None
                if record_to_save is not None:
                    self._start_save(record_to_save)
                self.stop_event.wait(0.01)
        except Exception as exc:
            logger.exception('Camera worker failed')
            with self.lock:
                self.error = str(exc) or 'Camera tracking failed. Try starting again.'
        finally:
            # Always release the camera and pose model, even after a driver error.
            try:
                if capture is not None:
                    capture.release()
            finally:
                try:
                    if processor is not None:
                        processor.close()
                finally:
                    with self.lock:
                        self.workout.pause(self.clock())
                        self._cancel_countdown()
                        self.tracker.cancel_calibration()
                        self.tracker.pause()
                        self.tracker.update(float('nan'), float('nan'), False, False)
                        self.camera_state = 'off'
                        self.jpeg = None

    def _start_save(self, record):
        # Save in a separate thread so preview updates continue. Allow one save at a time.
        self.history_thread = threading.Thread(
            target=self._save_record, args=(record,), name='repbuddy-history',
            daemon=False,
        )
        self.history_thread.start()

    def _save_record(self, record):
        try:
            if self.on_completed is not None:
                self.on_completed(asdict(record))
        except Exception as exc:
            # Connection errors may contain private database configuration.
            logger.error('Could not save completed set (%s)', type(exc).__name__)
            with self.lock:
                self.history_state = 'error'
                self.history_error = 'Your set could not be saved. Keep the app open and try saving again.'
        else:
            with self.lock:
                self.history_state = 'saved'
                self.history_error = None
                self.history_version += 1
