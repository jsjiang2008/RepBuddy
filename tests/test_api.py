import unittest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend.api import create_app
from backend.tracker import PushUpTracker


class FakeService:
    def __init__(self):
        self.tracker = PushUpTracker()
        self.commands = []

    def snapshot(self):
        return {**self.tracker.snapshot(), 'cameraState': 'off', 'error': None}

    def latest_frame(self):
        return 0, None

    def command(self, command, goal=None):
        self.commands.append(command)
        if command == 'start':
            self.tracker.start()
        elif command in ('stop', 'pause'):
            self.tracker.pause()
        elif command == 'reset':
            self.tracker.reset()
        elif command == 'goal':
            self.tracker.set_goal(goal)


def receive_until(ws, predicate):
    for _ in range(30):
        data = ws.receive_json()
        if predicate(data):
            return data
    raise AssertionError('Expected status was not received')


class ApiTests(unittest.TestCase):
    def test_connection_does_not_start_camera_and_commands_are_acknowledged(self):
        service = FakeService()
        with TestClient(create_app(service)) as client:
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
        with TestClient(create_app(FakeService())) as client:
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
        with TestClient(create_app(FakeService())) as client:
            with self.assertRaises(WebSocketDisconnect):
                with client.websocket_connect('/api/ws', headers={'origin': 'https://unrelated.example'}):
                    pass

    def test_last_client_disconnect_stops_camera(self):
        service = FakeService()
        with TestClient(create_app(service)) as client:
            with client.websocket_connect('/api/ws') as first:
                first.receive_json()
                with client.websocket_connect('/api/ws') as second:
                    second.receive_json()
                # This round-trip lets disconnect cleanup finish.
                first.send_json({'command': 'start', 'requestId': 1})
                receive_until(first, lambda data: data['ackId'] == 1)
                self.assertNotIn('stop', service.commands)
            self.assertIn('stop', service.commands)


class VideoTests(unittest.IsolatedAsyncioTestCase):
    async def test_mjpeg_stream_frames_without_starting_camera(self):
        service = FakeService()
        jpeg = b'\xff\xd8example-frame\xff\xd9'
        service.latest_frame = lambda: (1, jpeg)
        app = create_app(service)
        endpoint = next(route.endpoint for route in app.routes if route.path == '/api/video')

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
