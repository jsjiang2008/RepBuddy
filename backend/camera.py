"""One camera worker per app; HTTP and WebSocket clients share its latest frame."""
import logging
import math
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from uuid import uuid4

from .devices import list_video_devices, open_video_capture
from .tracker import PushUpTracker

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _CompletedSet:
    id: str
    completedAt: str
    reps: int
    goal: int
    durationSeconds: float


class CameraService:
    def __init__(self, camera_index=0, capture_factory=None, processor_factory=None,
                 device_provider=None, clock=time.monotonic, countdown_seconds=5,
                 on_completed=None):
        self.clock = clock
        self.tracker = PushUpTracker(clock=clock)
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
        self.lock = threading.RLock()
        self.control_lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread = None
        self.camera_state = 'off'
        self.error = None
        self.jpeg = None
        self.frame_id = 0

    def snapshot(self):
        with self.lock:
            countdown = (max(0, math.ceil(self.countdown_deadline - self.clock()))
                         if self.countdown_deadline is not None else 0)
            return {**self.tracker.snapshot(), 'cameraState': self.camera_state,
                    'error': self.error, 'cameraIndex': self.camera_index,
                    'countdownSeconds': countdown, 'historyState': self.history_state,
                    'historyError': self.history_error,
                    'historyVersion': self.history_version}

    def latest_frame(self):
        with self.lock:
            return self.frame_id, self.jpeg

    def list_cameras(self):
        with self.control_lock:
            cameras = self._available_cameras()
            with self.lock:
                return {'cameras': cameras, 'selectedIndex': self.camera_index}

    def _available_cameras(self):
        try:
            return self.device_provider()
        except Exception:
            logger.exception('Could not list cameras')
            raise RuntimeError('Could not list cameras. Reconnect your webcam and try again.') from None

    def _require_saved(self):
        if self.history_state == 'saving':
            raise ValueError('Wait for your completed set to finish saving.')
        if self.history_state == 'error':
            raise ValueError('Retry saving your completed set before starting or resetting.')

    def _clear_completed_set(self):
        self.completed_record = None
        self.history_state = None
        self.history_error = None

    def _cancel_countdown(self):
        self.start_requested = False
        self.countdown_deadline = None

    def command(self, command, goal=None, camera_index=None):
        # Serialize commands, including disconnect/shutdown, without blocking
        # frame/status reads while a camera driver is releasing its handle.
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
            if command in ('stop', 'reset'):
                if command == 'reset':
                    with self.lock:
                        self._require_saved()
                        # Stop counting under the same lock as the save guard;
                        # a final rep must not race between the check and stop.
                        self._cancel_countdown()
                        self.tracker.pause()
                        self.stop_event.set()
                self._stop()
                if command == 'reset':
                    with self.lock:
                        self.tracker.reset()
                        self.error = None
                        self._clear_completed_set()
                return
            with self.lock:
                if command == 'goal':
                    if (self.camera_state == 'starting' or self.start_requested or
                            self.countdown_deadline is not None):
                        raise ValueError('Pause or reset the set before changing its goal.')
                    self.tracker.set_goal(goal)
                elif command == 'pause':
                    self._cancel_countdown()
                    self.tracker.pause()
                    if self.camera_state == 'starting':
                        self.stop_event.set()
                elif command == 'start':
                    self._require_saved()
                    if self.thread is not None and self.thread.is_alive():
                        if self.stop_event.is_set():
                            raise ValueError('The camera is stopping. Try Start again in a moment.')
                        if (self.tracker.running or self.start_requested or
                                self.countdown_deadline is not None):
                            return
                    if self.tracker.counter >= self.tracker.goal:
                        self.tracker.reset()
                        self._clear_completed_set()
                    self.start_requested = True
                    if self.thread is not None and self.thread.is_alive():
                        return  # The next valid preview frame starts the countdown.
                    self.error = None
                    self.jpeg = None
                    self.camera_state = 'starting'
                    self.stop_event.clear()
                    self.thread = threading.Thread(target=self._run, daemon=True,
                                                   name='repbuddy-camera')
                    self.thread.start()
                else:
                    raise ValueError('Unknown workout command.')

    def _stop(self):
        with self.lock:
            self._cancel_countdown()
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
            self.tracker.in_plank = False
            self.tracker.has_pose = False

    def close(self):
        """Release the webcam and give an in-flight history write time to finish."""
        with self.control_lock:
            self._stop()
            history_thread = self.history_thread
            if history_thread is not None and history_thread.is_alive():
                history_thread.join(timeout=5)

    def _run(self):
        capture = processor = None
        try:
            # Heavy libraries and hardware are initialized only after Start.
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
                    if self.start_requested:
                        self.countdown_deadline = self.clock() + self.countdown_seconds
                        self.start_requested = False
                    if (self.countdown_deadline is not None and
                            self.clock() >= self.countdown_deadline):
                        self.countdown_deadline = None
                        self.tracker.start()
                    was_completed = self.tracker.counter >= self.tracker.goal
                    self.tracker.update(left, right, in_plank, has_pose)
                    self.jpeg = encoded.tobytes()
                    self.frame_id += 1
                    if (not was_completed and self.tracker.counter >= self.tracker.goal
                            and self.on_completed is not None):
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
            try:
                if capture is not None:
                    capture.release()
            finally:
                try:
                    if processor is not None:
                        processor.close()
                finally:
                    with self.lock:
                        self._cancel_countdown()
                        self.tracker.pause()
                        self.tracker.in_plank = False
                        self.tracker.has_pose = False
                        self.camera_state = 'off'
                        self.jpeg = None

    def _start_save(self, record):
        # A separate worker keeps preview responsive and lets retries run even
        # after the webcam has been stopped. Only one save may be in flight.
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
