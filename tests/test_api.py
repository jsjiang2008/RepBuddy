"""Test browser requests and controls without opening a real webcam."""
import unittest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend.api import create_app
from backend.camera import CameraService
from backend.tracker import PushUpTracker


class FakeService:
    # This small substitute records commands and follows the real tracker state.
    def __init__(self, frame: tuple[int, bytes | None] = (0, None)):
        self.tracker = PushUpTracker()
        self.commands = []
        self.frame = frame
        self.camera_index = 0

    def snapshot(self):
        return {**self.tracker.snapshot(), 'cameraState': 'off', 'error': None}

    def latest_frame(self) -> tuple[int, bytes | None]:
        return self.frame

    def list_cameras(self):
        return {'cameras': [{'index': 0, 'name': 'Built-in camera'},
                            {'index': 1, 'name': 'USB webcam'}], 'selectedIndex': self.camera_index}

    def close(self):
        self.command('stop')

    def command(self, command, goal=None, camera_index=None):
        self.commands.append(command)
        if command == 'start':
            self.tracker.start()
        elif command in ('stop', 'pause'):
            self.tracker.cancel_calibration()
            self.tracker.pause()
        elif command == 'reset':
            self.tracker.reset()
        elif command == 'goal':
            self.tracker.set_goal(goal)
        elif command == 'calibrate':
            self.tracker.begin_calibration()
        elif command == 'cancelCalibration':
            self.tracker.cancel_calibration()
        elif command == 'clearCalibration':
            self.tracker.clear_calibration()
        elif command == 'camera':
            if camera_index not in (0, 1):
                raise ValueError('That webcam is no longer available.')
            self.camera_index = camera_index


class FakeHistory:
    # Simulate an available database or a connection failure without real data.
    def __init__(self):
        self.initialized = False
        self.pages = []
        self.unavailable = False

    def initialize(self):
        self.initialized = True

    def check(self):
        if self.unavailable:
            raise RuntimeError('secret connection information')
        return True

    def save(self, record):
        pass

    def list_workouts(self, limit, offset):
        self.check()
        self.pages.append((limit, offset))
        return {'workouts': [], 'total': 0,
                'summary': {'totalSets': 0, 'totalReps': 0, 'weekReps': 0, 'bestSet': 0}}


def test_app(service=None, history=None):
    # Give each API test a fresh app with controlled replacements.
    return create_app(service if service is not None else FakeService(),
                      history if history is not None else FakeHistory())


def receive_until(ws, predicate):
    # Skip earlier updates until the expected command result arrives.
    for _ in range(30):
        data = ws.receive_json()
        if predicate(data):
            return data
    raise AssertionError('Expected status was not received')


class ApiTests(unittest.TestCase):
    def test_workout_settings_are_acknowledged_and_invalid_plans_do_not_replace_them(self):
        # Settings use the real service without opening any camera.
        service = CameraService()
        with TestClient(test_app(service)) as client:
            with client.websocket_connect('/api/ws') as ws:
                ws.receive_json()
                ws.send_json({'command': 'configureWorkout', 'sets': 3, 'restSeconds': 45, 'requestId': 1})
                result = receive_until(ws, lambda data: data['ackId'] == 1)
                self.assertIsNone(result['commandError'])
                self.assertEqual((result['totalSets'], result['restSeconds']), (3, 45))
                self.assertEqual(result['cameraState'], 'off')
                for request_id, settings in enumerate(({'sets': 0, 'restSeconds': 60},
                                                        {'sets': 2, 'restSeconds': 301}, {}), 2):
                    ws.send_json({'command': 'configureWorkout', **settings, 'requestId': request_id})
                    result = receive_until(ws, lambda data: data['ackId'] == request_id)
                    self.assertIsNotNone(result['commandError'])
                    self.assertEqual((result['totalSets'], result['restSeconds']), (3, 45))
                ws.send_json({'command': 'skipRest', 'requestId': 5})
                result = receive_until(ws, lambda data: data['ackId'] == 5)
                self.assertIsNotNone(result['commandError'])

    def test_calibration_commands_are_acknowledged_without_starting_a_workout(self):
        # Calibration opens a separate workflow and never starts the session timer.
        with TestClient(test_app()) as client:
            with client.websocket_connect('/api/ws') as ws:
                ws.receive_json()
                for request_id, (command, state) in enumerate((
                        ('calibrate', 'hold_up'), ('cancelCalibration', 'idle'),
                        ('clearCalibration', 'idle')), 1):
                    ws.send_json({'command': command, 'requestId': request_id})
                    result = receive_until(ws, lambda data: data['ackId'] == request_id)
                    self.assertIsNone(result['commandError'])
                    self.assertEqual(result['calibrationState'], state)
                    self.assertFalse(result['running'])
                    self.assertEqual(result['elapsedSeconds'], 0)

    def test_connection_does_not_start_camera_and_commands_are_acknowledged(self):
        # Check that opening the page leaves the camera off and controls get replies.
        service = FakeService()
        with TestClient(test_app(service)) as client:
            self.assertEqual(client.get('/api/health').json(), {'status': 'ok'})
            with client.websocket_connect('/api/ws', headers={'origin': 'http://127.0.0.1:5173'}) as ws:
                self.assertFalse(ws.receive_json()['running'])
                self.assertEqual(service.commands, [])
                for request_id, command in enumerate(('start', 'pause', 'reset', 'stop'), 1):
                    ws.send_json({'command': command, 'requestId': request_id})
                    result = receive_until(ws, lambda data: data['ackId'] == request_id)
                    self.assertIsNone(result['commandError'])
                    self.assertEqual(result['running'], command == 'start')
        self.assertEqual(service.commands[-1], 'stop')

    def test_invalid_command_does_not_disconnect_client(self):
        # Reject invalid input while keeping the connection available for valid controls.
        with TestClient(test_app()) as client:
            with client.websocket_connect('/api/ws') as ws:
                ws.receive_json()
                ws.send_text('not-json')
                receive_until(ws, lambda data: bool(data['commandError']))
                ws.send_json({'command': 'goal', 'goal': 5, 'requestId': 1})
                result = receive_until(ws, lambda data: data['ackId'] == 1)
                self.assertEqual(result['goal'], 5)
                self.assertIsNone(result['commandError'])
                ws.send_json({'command': 'goal', 'goal': 999, 'requestId': 2})
                result = receive_until(ws, lambda data: data['ackId'] == 2)
                self.assertIsNotNone(result['commandError'])

    def test_external_origins_are_rejected(self):
        # Prevent another website from controlling the local webcam.
        with TestClient(test_app()) as client:
            with self.assertRaises(WebSocketDisconnect):
                with client.websocket_connect('/api/ws', headers={'origin': 'https://unrelated.example'}):
                    pass

    def test_last_client_disconnect_stops_camera(self):
        # Keep the camera available until the last connected page closes.
        service = FakeService()
        with TestClient(test_app(service)) as client:
            with client.websocket_connect('/api/ws') as first:
                first.receive_json()
                with client.websocket_connect('/api/ws') as second:
                    second.receive_json()
                # This request gives the disconnected page time to finish cleanup.
                first.send_json({'command': 'start', 'requestId': 1})
                receive_until(first, lambda data: data['ackId'] == 1)
                self.assertNotIn('stop', service.commands)
            self.assertIn('stop', service.commands)

    def test_cameras_list_without_starting_and_selection_is_acknowledged(self):
        # Check camera discovery and selection without opening video.
        service = FakeService()
        with TestClient(test_app(service)) as client:
            response = client.get('/api/cameras')
            self.assertEqual(response.json()['cameras'][1]['name'], 'USB webcam')
            self.assertEqual(service.commands, [])
            with client.websocket_connect('/api/ws') as ws:
                ws.receive_json()
                ws.send_json({'command': 'camera', 'cameraIndex': 1, 'requestId': 1})
                result = receive_until(ws, lambda data: data['ackId'] == 1)
                self.assertIsNone(result['commandError'])
                self.assertEqual(service.camera_index, 1)
                ws.send_json({'command': 'camera', 'requestId': 2})
                result = receive_until(ws, lambda data: data['ackId'] == 2)
                self.assertIsNotNone(result['commandError'])
                self.assertEqual(service.camera_index, 1)

    def test_history_pagination_and_database_errors(self):
        # Check history page limits and useful messages when the database fails.
        history = FakeHistory()
        with TestClient(test_app(history=history)) as client:
            self.assertTrue(history.initialized)
            response = client.get('/api/history?limit=10&offset=20')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(history.pages, [(10, 20)])
            self.assertEqual(response.headers['cache-control'], 'no-store')
            for query in ('limit=0', 'limit=101', 'offset=-1', 'offset=not-a-number'):
                self.assertEqual(client.get('/api/history?' + query).status_code, 422)
            history.unavailable = True
            response = client.get('/api/history')
            self.assertEqual(response.status_code, 503)
            self.assertNotIn('secret', response.text)
            self.assertEqual(client.get('/api/health').status_code, 503)


class VideoTests(unittest.IsolatedAsyncioTestCase):
    async def test_mjpeg_stream_frames_without_starting_camera(self):
        # Check the video message format using a prepared image.
        jpeg = b'\xff\xd8example-frame\xff\xd9'
        service = FakeService(frame=(1, jpeg))
        app = test_app(service)
        endpoint = next(
            route.endpoint
            for route in app.routes
            if isinstance(route, APIRoute) and route.path == '/api/video'
        )

        class Request:
            async def is_disconnected(self):
                return False

        response = await endpoint(Request())
        self.assertIn('multipart/x-mixed-replace', response.media_type)
        self.assertEqual(response.headers['cache-control'], 'no-store')
        body = await anext(response.body_iterator)
        self.assertTrue(body.startswith(b'--frame\r\nContent-Type: image/jpeg'))
        self.assertIn(f'Content-Length: {len(jpeg)}'.encode(), body)
        self.assertTrue(body.endswith(jpeg + b'\r\n'))
        self.assertEqual(service.commands, [])
        await response.body_iterator.aclose()
