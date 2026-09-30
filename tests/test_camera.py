import time
import unittest
import numpy as np

from backend.camera import CameraService


class Capture:
    def __init__(self, opened=True):
        self.opened = opened
        self.released = False

    def isOpened(self):
        return self.opened

    def set(self, *_):
        pass

    def read(self):
        return True, np.zeros((48, 64, 3), dtype=np.uint8)

    def release(self):
        self.released = True


class Processor:
    closed = False

    def process(self, frame):
        return frame, 170, 170, True, True

    def close(self):
        self.closed = True


def wait_until(predicate):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError('Camera state transition timed out')


class CameraTests(unittest.TestCase):
    def test_single_worker_preview_pause_reset_release(self):
        capture, processor = Capture(), Processor()
        opened = []
        def factory(index):
            opened.append(index)
            return capture
        service = CameraService(capture_factory=factory, processor_factory=lambda: processor)
        self.assertIsNone(service.thread)
        try:
            service.command('start')
            wait_until(lambda: service.latest_frame()[1] is not None)
            service.command('start')
            self.assertEqual(len(opened), 1)
            self.assertTrue(service.latest_frame()[1].startswith(b'\xff\xd8'))
            service.command('pause')
            self.assertFalse(service.snapshot()['running'])
            self.assertEqual(service.snapshot()['cameraState'], 'ready')
            service.command('reset')
            self.assertTrue(capture.released)
            self.assertTrue(processor.closed)
            self.assertIsNone(service.latest_frame()[1])
            self.assertEqual(service.snapshot()['elapsedSeconds'], 0)
        finally:
            service.command('stop')

    def test_camera_failure_is_reported_and_released(self):
        capture = Capture(opened=False)
        service = CameraService(capture_factory=lambda _: capture, processor_factory=Processor)
        with self.assertLogs('backend.camera', level='ERROR'):
            service.command('start')
            wait_until(lambda: service.snapshot()['error'] is not None)
            service.command('stop')
        self.assertTrue(capture.released)
        self.assertFalse(service.snapshot()['running'])
        self.assertIn('webcam', service.snapshot()['error'])
