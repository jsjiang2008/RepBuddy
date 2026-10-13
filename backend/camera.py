"""One camera worker per app; HTTP and WebSocket clients share its latest frame."""
import logging
import threading

from .tracker import PushUpTracker

logger = logging.getLogger(__name__)


class CameraService:
    def __init__(self, camera_index=0, capture_factory=None, processor_factory=None):
        self.tracker = PushUpTracker()
        self.camera_index = camera_index
        self.capture_factory = capture_factory
        self.processor_factory = processor_factory
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
            return {**self.tracker.snapshot(), 'cameraState': self.camera_state,
                    'error': self.error}

    def latest_frame(self):
        with self.lock:
            return self.frame_id, self.jpeg

    def command(self, command, goal=None):
        # Serialize commands, including disconnect/shutdown, without blocking
        # frame/status reads while a camera driver is releasing its handle.
        with self.control_lock:
            if command in ('stop', 'reset'):
                self._stop()
                if command == 'reset':
                    with self.lock:
                        self.tracker.reset()
                        self.error = None
                return
            with self.lock:
                if command == 'goal':
                    if self.camera_state == 'starting':
                        raise ValueError('Wait for the camera to start before changing the goal.')
                    self.tracker.set_goal(goal)
                elif command == 'pause':
                    self.tracker.pause()
                    if self.camera_state == 'starting':
                        self.stop_event.set()
                elif command == 'start':
                    if self.thread is not None and self.thread.is_alive():
                        if self.stop_event.is_set():
                            raise ValueError('The camera is stopping. Try Start again in a moment.')
                        if self.camera_state == 'ready':
                            self.tracker.start()
                        return
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

    def _run(self):
        capture = processor = None
        try:
            # Heavy libraries and hardware are initialized only after Start.
            import cv2
            factory = self.capture_factory or cv2.VideoCapture
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
            with self.lock:
                if self.stop_event.is_set():
                    return
                self.camera_state = 'ready'
                self.tracker.start()
            while not self.stop_event.is_set():
                success, frame = capture.read()
                if not success:
                    raise RuntimeError('The webcam stopped sending frames. Check the camera and try Start again.')
                frame, left, right, in_plank, has_pose = processor.process(frame)
                success, encoded = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                if not success:
                    raise RuntimeError('Could not encode the camera preview.')
                with self.lock:
                    if self.stop_event.is_set():
                        break
                    self.tracker.update(left, right, in_plank, has_pose)
                    self.jpeg = encoded.tobytes()
                    self.frame_id += 1
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
                        self.tracker.pause()
                        self.tracker.in_plank = False
                        self.tracker.has_pose = False
                        self.camera_state = 'off'
                        self.jpeg = None