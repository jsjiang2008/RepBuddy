import sys
import threading
import time
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import UUID

import numpy as np

from backend.camera import CameraService
from backend.devices import list_video_devices, open_video_capture


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
    angle = 170

    def process(self, frame):
        angle = self.angle
        return frame, angle, angle, True, True

    def close(self):
        self.closed = True


def wait_until(predicate):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError('Camera state transition timed out')


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def wait_for_frame(service):
    previous_id = service.latest_frame()[0]
    wait_until(lambda: service.latest_frame()[0] > previous_id)


def finish_set(service, processor, clock):
    wait_until(lambda: service.snapshot()['stage'] == 'up')
    for rep in range(service.snapshot()['goal']):
        clock.advance(1)
        processor.angle = 70
        wait_until(lambda: service.snapshot()['stage'] == 'down')
        clock.advance(1)
        processor.angle = 170
        wait_until(lambda: service.snapshot()['reps'] == rep + 1)


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
            _, jpeg = service.latest_frame()
            if jpeg is None:
                self.fail('Expected an encoded camera frame.')
            self.assertTrue(jpeg.startswith(b'\xff\xd8'))
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

    def test_camera_selection_validates_available_devices_and_requires_stop(self):
        capture = Capture()
        factory = Mock(return_value=capture)
        devices = [{'index': 0, 'name': 'Built-in'}, {'index': 2, 'name': 'USB camera'}]
        service = CameraService(capture_factory=factory, processor_factory=Processor,
                                device_provider=lambda: devices)
        self.assertEqual(service.list_cameras(), {'cameras': devices, 'selectedIndex': 0})
        factory.assert_not_called()
        for invalid in (None, True, '2', -1, 1):
            with self.subTest(camera_index=invalid), self.assertRaises(ValueError):
                service.command('camera', camera_index=invalid)
        service.command('camera', camera_index=2)
        self.assertEqual(service.snapshot()['cameraIndex'], 2)
        try:
            service.command('start')
            wait_until(lambda: service.snapshot()['cameraState'] == 'ready')
            factory.assert_called_once_with(2)
            with self.assertRaisesRegex(ValueError, 'Stop the camera'):
                service.command('camera', camera_index=0)
            service.command('pause')
            with self.assertRaisesRegex(ValueError, 'Stop the camera'):
                service.command('camera', camera_index=0)
            service.command('stop')
            service.command('camera', camera_index=0)
            self.assertEqual(service.list_cameras()['selectedIndex'], 0)
        finally:
            service.command('stop')

    def test_windows_enumeration_and_capture_use_matching_backend_without_probing(self):
        import cv2

        enumerate_devices = Mock(return_value=[SimpleNamespace(index=2, name='USB camera')])
        package = SimpleNamespace(enumerate_cameras=enumerate_devices)
        with patch.dict(sys.modules, {'cv2_enumerate_cameras': package}), \
                patch('backend.devices.sys.platform', 'win32'), \
                patch('cv2.VideoCapture') as capture:
            self.assertEqual(list_video_devices(), [{'index': 2, 'name': 'USB camera'}])
            enumerate_devices.assert_called_once_with(cv2.CAP_DSHOW)
            capture.assert_not_called()
            open_video_capture(2)
            capture.assert_called_once_with(2, cv2.CAP_DSHOW)

    def test_countdown_starts_after_first_frame_and_excludes_time_and_reps(self):
        clock, processor = Clock(), Processor()
        reading, release_frame = threading.Event(), threading.Event()

        class SlowCapture(Capture):
            def read(self):
                reading.set()
                release_frame.wait(timeout=5)
                return super().read()

        service = CameraService(capture_factory=lambda _: SlowCapture(),
                                processor_factory=lambda: processor, clock=clock)
        try:
            service.command('start')
            self.assertTrue(reading.wait(timeout=5))
            clock.advance(100)
            self.assertEqual(service.snapshot()['cameraState'], 'starting')
            self.assertEqual(service.snapshot()['countdownSeconds'], 0)
            self.assertEqual(service.snapshot()['elapsedSeconds'], 0)
            release_frame.set()
            wait_until(lambda: service.snapshot()['countdownSeconds'] == 5)
            self.assertIsNotNone(service.latest_frame()[1])
            clock.advance(2)
            service.command('start')
            self.assertEqual(service.snapshot()['countdownSeconds'], 3)
            with self.assertRaises(ValueError):
                service.command('goal', goal=5)
            processor.angle = 70
            wait_for_frame(service)
            processor.angle = 170
            wait_for_frame(service)
            self.assertFalse(service.snapshot()['running'])
            self.assertEqual(service.snapshot()['reps'], 0)
            self.assertIsNone(service.snapshot()['stage'])
            self.assertEqual(service.snapshot()['elapsedSeconds'], 0)
            clock.advance(3)
            wait_until(lambda: service.snapshot()['running'])
            self.assertEqual(service.snapshot()['countdownSeconds'], 0)
            self.assertEqual(service.snapshot()['elapsedSeconds'], 0)
            service.command('start')
            self.assertTrue(service.snapshot()['running'])
            self.assertEqual(service.snapshot()['countdownSeconds'], 0)
            clock.advance(2)
            service.command('pause')
            self.assertEqual(service.snapshot()['elapsedSeconds'], 2)
            service.command('start')
            wait_until(lambda: service.snapshot()['countdownSeconds'] == 5)
            clock.advance(4)
            wait_for_frame(service)
            self.assertFalse(service.snapshot()['running'])
            self.assertEqual(service.snapshot()['elapsedSeconds'], 2)
            clock.advance(1)
            wait_until(lambda: service.snapshot()['running'])
            self.assertEqual(service.snapshot()['elapsedSeconds'], 2)
        finally:
            release_frame.set()
            service.command('stop')

    def test_cancelled_countdown_never_starts_later(self):
        for command in ('pause', 'stop', 'reset'):
            with self.subTest(command=command):
                clock, capture = Clock(), Capture()
                saved = Mock()
                service = CameraService(capture_factory=lambda _: capture,
                                        processor_factory=Processor, clock=clock,
                                        on_completed=saved)
                try:
                    service.command('start')
                    wait_until(lambda: service.snapshot()['countdownSeconds'] == 5)
                    clock.advance(2)
                    service.command(command)
                    clock.advance(30)
                    if command == 'pause':
                        wait_for_frame(service)
                        self.assertEqual(service.snapshot()['cameraState'], 'ready')
                    else:
                        self.assertTrue(capture.released)
                    self.assertEqual(service.snapshot()['countdownSeconds'], 0)
                    self.assertFalse(service.snapshot()['running'])
                    self.assertEqual(service.snapshot()['elapsedSeconds'], 0)
                    self.assertEqual(service.snapshot()['reps'], 0)
                    saved.assert_not_called()
                finally:
                    service.command('stop')

    def test_completion_saves_once_and_allows_new_set_after_save(self):
        clock, processor = Clock(), Processor()
        save_started, save_allowed = threading.Event(), threading.Event()
        records = []

        def save(record):
            records.append(record)
            save_started.set()
            save_allowed.wait(timeout=5)

        service = CameraService(capture_factory=lambda _: Capture(),
                                processor_factory=lambda: processor, clock=clock,
                                countdown_seconds=0, on_completed=save)
        try:
            service.command('goal', goal=5)
            service.command('start')
            finish_set(service, processor, clock)
            self.assertTrue(save_started.wait(timeout=5))
            self.assertEqual(service.snapshot()['historyState'], 'saving')
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]['reps'], 5)
            self.assertEqual(records[0]['goal'], 5)
            self.assertEqual(records[0]['durationSeconds'], 10)
            self.assertEqual(str(UUID(records[0]['id'])), records[0]['id'])
            self.assertIsNotNone(datetime.fromisoformat(records[0]['completedAt']).tzinfo)
            with self.assertRaisesRegex(ValueError, 'saving'):
                service.command('reset')
            with self.assertRaisesRegex(ValueError, 'saving'):
                service.command('start')
            service.command('retrySave')
            wait_for_frame(service)  # A slow history write does not freeze preview.
            self.assertEqual(len(records), 1)
            save_allowed.set()
            wait_until(lambda: service.snapshot()['historyState'] == 'saved')
            self.assertEqual(service.snapshot()['historyVersion'], 1)
            wait_for_frame(service)
            self.assertEqual(len(records), 1)
            service.command('start')
            wait_until(lambda: service.snapshot()['running'])
            self.assertEqual(service.snapshot()['reps'], 0)
            self.assertEqual(service.snapshot()['elapsedSeconds'], 0)
            self.assertIsNone(service.snapshot()['historyState'])
            self.assertEqual(service.snapshot()['historyVersion'], 1)
        finally:
            save_allowed.set()
            service.command('stop')
            if service.history_thread is not None:
                service.history_thread.join(timeout=5)

    def test_failed_save_retains_record_for_retry_after_camera_stop(self):
        clock, processor = Clock(), Processor()
        records = []

        def save(record):
            records.append(record.copy())
            if len(records) == 1:
                record['id'] = 'callback mutation must not change the retry'
                raise RuntimeError('private disk path and internal database details')

        service = CameraService(capture_factory=lambda _: Capture(),
                                processor_factory=lambda: processor, clock=clock,
                                countdown_seconds=0, on_completed=save)
        try:
            service.command('goal', goal=5)
            service.command('start')
            with self.assertLogs('backend.camera', level='ERROR'):
                finish_set(service, processor, clock)
                wait_until(lambda: service.snapshot()['historyState'] == 'error')
            self.assertNotIn('private', service.snapshot()['historyError'])
            self.assertEqual(service.snapshot()['historyVersion'], 0)
            for command in ('start', 'reset'):
                with self.subTest(command=command), self.assertRaisesRegex(ValueError, 'Retry'):
                    service.command(command)
            service.command('stop')
            self.assertEqual(service.snapshot()['reps'], 5)
            clock.advance(50)
            service.command('retrySave')
            wait_until(lambda: service.snapshot()['historyState'] == 'saved')
            self.assertEqual(records[0], records[1])
            self.assertEqual(service.snapshot()['historyVersion'], 1)
            self.assertIsNone(service.snapshot()['historyError'])
            service.command('reset')
            self.assertEqual(service.snapshot()['reps'], 0)
            self.assertIsNone(service.snapshot()['historyState'])
        finally:
            service.command('stop')
            if service.history_thread is not None:
                service.history_thread.join(timeout=5)

    def test_completion_without_history_callback_remains_usable(self):
        clock, processor = Clock(), Processor()
        service = CameraService(capture_factory=lambda _: Capture(),
                                processor_factory=lambda: processor, clock=clock,
                                countdown_seconds=0)
        try:
            service.command('goal', goal=5)
            service.command('start')
            finish_set(service, processor, clock)
            self.assertIsNone(service.snapshot()['historyState'])
            self.assertTrue(service.snapshot()['completed'])
            self.assertFalse(service.snapshot()['running'])
            service.command('reset')
            self.assertEqual(service.snapshot()['reps'], 0)
        finally:
            service.command('stop')

    def test_close_waits_for_in_flight_history_write(self):
        clock, processor = Clock(), Processor()
        saving, finish_saving, closed = threading.Event(), threading.Event(), threading.Event()

        def save(_record):
            saving.set()
            finish_saving.wait(timeout=5)

        service = CameraService(capture_factory=lambda _: Capture(),
                                processor_factory=lambda: processor, clock=clock,
                                countdown_seconds=0, on_completed=save)

        def close():
            service.close()
            closed.set()

        shutdown = threading.Thread(target=close)
        try:
            service.command('goal', goal=5)
            service.command('start')
            finish_set(service, processor, clock)
            self.assertTrue(saving.wait(timeout=5))
            shutdown.start()
            wait_until(lambda: service.snapshot()['cameraState'] == 'off')
            self.assertFalse(closed.is_set())
            finish_saving.set()
            self.assertTrue(closed.wait(timeout=5))
            self.assertEqual(service.snapshot()['historyState'], 'saved')
            self.assertFalse(service.history_thread.is_alive())
        finally:
            finish_saving.set()
            if shutdown.ident is not None:
                shutdown.join(timeout=5)
            service.close()
