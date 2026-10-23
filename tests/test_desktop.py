"""Check private desktop access and an isolated bundled database."""
import os
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend.desktop import DesktopAccess
from backend.desktop_database import DesktopDatabase
from backend.history import HistoryRepository


class DesktopAccessTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()

        @app.get('/api/health')
        async def health():
            return {'status': 'ok'}

        @app.websocket('/api/ws')
        async def websocket(ws: WebSocket):
            await ws.accept()
            await ws.send_json({'connected': True})
            await ws.close()

        self.client = TestClient(DesktopAccess(app, 'private-test-session-token'))

    def test_http_requires_the_desktop_token(self):
        self.assertEqual(self.client.get('/api/health').status_code, 403)
        self.assertEqual(self.client.get('/api/health', headers={'X-RepBuddy-Token': 'wrong'}).status_code, 403)
        response = self.client.get('/api/health', headers={'X-RepBuddy-Token': 'private-test-session-token'})
        self.assertEqual(response.json(), {'status': 'ok'})

    def test_websocket_requires_the_same_token(self):
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect('/api/ws'):
                pass
        with self.client.websocket_connect('/api/ws', headers={'X-RepBuddy-Token': 'private-test-session-token'}) as ws:
            self.assertEqual(ws.receive_json(), {'connected': True})


@unittest.skipUnless(os.environ.get('REPBUDDY_TEST_POSTGRES'), 'Set REPBUDDY_TEST_POSTGRES to test the bundled database.')
class DesktopDatabaseTests(unittest.TestCase):
    def test_first_launch_restart_and_saved_history(self):
        # Use a newly created cluster so existing workouts cannot be touched.
        with tempfile.TemporaryDirectory(prefix='repbuddy-desktop-test-') as temporary:
            data = Path(temporary)
            database = DesktopDatabase(Path(os.environ['REPBUDDY_TEST_POSTGRES']), data)
            try:
                repository = HistoryRepository(database.start())
                repository.initialize()
                record = {'id': str(uuid4()), 'completedAt': '2026-10-22T12:00:00Z',
                          'reps': 5, 'goal': 5, 'durationSeconds': 12.5}
                self.assertTrue(repository.save(record))
                database.close()
                repository = HistoryRepository(database.start())
                repository.initialize()
                self.assertEqual(repository.list_workouts()['total'], 1)
                self.assertEqual(repository.list_workouts()['workouts'][0]['id'], record['id'])
            finally:
                database.close()
            self.assertFalse(database.started)
