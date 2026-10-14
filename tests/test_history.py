"""Database integration tests require an explicit TEST_DATABASE_URL.

Every integration run creates a unique schema and only removes that schema.
No SQLite substitute or existing workout data is used.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import os
import unittest
from unittest.mock import patch
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from backend.history import HistoryRepository


def completed_set(**changes):
    record = {
        'id': str(uuid4()),
        'completedAt': '2026-10-14T12:00:00Z',
        'reps': 10,
        'goal': 10,
        'durationSeconds': 24.5,
    }
    return {**record, **changes}


class HistoryValidationTests(unittest.TestCase):
    def setUp(self):
        self.repository = HistoryRepository('postgresql://unused.invalid/unused')

    def test_invalid_records_are_rejected_before_connecting(self):
        invalid = [
            {'id': 'bad-id'}, {'goal': 11}, {'goal': True}, {'reps': 9},
            {'reps': True}, {'durationSeconds': -1}, {'durationSeconds': True},
            {'durationSeconds': float('nan')}, {'durationSeconds': float('inf')},
            {'durationSeconds': 10 ** 1000}, {'completedAt': 'not-a-date'},
            {'completedAt': '2026-10-14T12:00:00'},
            {'completedAt': datetime(2026, 10, 14)},
        ]
        with patch('backend.history.psycopg.connect') as connect:
            for changes in invalid:
                with self.subTest(changes=changes), self.assertRaises(ValueError):
                    self.repository.save(completed_set(**changes))
            connect.assert_not_called()

    def test_pagination_is_bounded_before_connecting(self):
        with patch('backend.history.psycopg.connect') as connect:
            for limit, offset in [(0, 0), (101, 0), (True, 0), (20, -1), (20, True)]:
                with self.subTest(limit=limit, offset=offset), self.assertRaises(ValueError):
                    self.repository.list_workouts(limit, offset)
            connect.assert_not_called()


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'), 'Set TEST_DATABASE_URL to run PostgreSQL integration tests.')
class HistoryIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base_url = os.environ['TEST_DATABASE_URL']
        cls.schema = f'repbuddy_test_{uuid4().hex}'
        with psycopg.connect(cls.base_url, connect_timeout=5) as connection:
            connection.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(cls.schema)))
        cls.database_url = make_conninfo(cls.base_url, options=f'-c search_path={cls.schema}')
        cls.repository = HistoryRepository(cls.database_url)
        try:
            cls.repository.initialize()
        except BaseException:
            cls.tearDownClass()
            raise

    @classmethod
    def tearDownClass(cls):
        # This name is generated above, never supplied by users or read from a URL.
        if not cls.schema.startswith('repbuddy_test_'):
            raise RuntimeError('Refusing to remove an unrelated schema.')
        with psycopg.connect(cls.base_url, connect_timeout=5) as connection:
            connection.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(cls.schema)))

    def setUp(self):
        with psycopg.connect(self.database_url, connect_timeout=5) as connection:
            connection.execute('TRUNCATE workouts')

    def test_migrations_are_repeatable_and_safe_during_concurrent_startup(self):
        with ThreadPoolExecutor(max_workers=4) as workers:
            list(workers.map(lambda _: HistoryRepository(self.database_url).initialize(), range(4)))
        with psycopg.connect(self.database_url, connect_timeout=5) as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM repbuddy_schema_migrations').fetchone()[0], 1)
        self.assertTrue(self.repository.check())

    def test_saved_set_survives_repository_restart_and_duplicate_save(self):
        record = completed_set(completedAt='2026-10-14T08:00:00-04:00')
        self.assertTrue(self.repository.save(record))
        restarted = HistoryRepository(self.database_url)
        self.assertFalse(restarted.save(record))
        result = restarted.list_workouts()
        self.assertEqual(result['total'], 1)
        self.assertEqual(result['workouts'], [{**record, 'completedAt': '2026-10-14T12:00:00Z'}])

    def test_camera_completion_is_saved_and_visible_after_app_restart(self):
        import time
        import numpy as np
        from fastapi.testclient import TestClient
        from backend.api import create_app
        from backend.camera import CameraService

        class Capture:
            released = False

            def isOpened(self):
                return True

            def set(self, *_):
                pass

            def read(self):
                return True, np.zeros((48, 64, 3), dtype=np.uint8)

            def release(self):
                self.released = True

        class Processor:
            frame_number = 0

            def process(self, frame):
                angle = (170, 70, 170)[self.frame_number % 3]
                self.frame_number += 1
                return frame, angle, angle, True, True

            def close(self):
                pass

        capture = Capture()
        service = CameraService(capture_factory=lambda _: capture, processor_factory=Processor,
                                countdown_seconds=0, on_completed=self.repository.save)
        with TestClient(create_app(service, self.repository)) as client:
            service.command('goal', 5)
            service.command('start')
            deadline = time.monotonic() + 10
            while service.snapshot()['historyState'] != 'saved' and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertEqual(service.snapshot()['historyState'], 'saved')
            self.assertEqual(service.snapshot()['historyVersion'], 1)
            saved = client.get('/api/history').json()
            self.assertEqual(saved['total'], 1)
            self.assertEqual(saved['workouts'][0]['reps'], 5)
        self.assertTrue(capture.released)

        # A new app and database connection must load the same saved set.
        with TestClient(create_app(history=HistoryRepository(self.database_url))) as client:
            for _ in range(2):
                with client.websocket_connect('/api/ws') as ws:
                    self.assertFalse(ws.receive_json()['running'])
                self.assertEqual(client.get('/api/history').json(), saved)

    def test_simultaneous_retries_save_one_row(self):
        record = completed_set()
        with ThreadPoolExecutor(max_workers=4) as workers:
            inserted = list(workers.map(lambda _: self.repository.save(record), range(4)))
        self.assertEqual(inserted.count(True), 1)
        self.assertEqual(self.repository.list_workouts()['total'], 1)

    def test_weekly_summary_is_utc_and_independent_of_pagination(self):
        records = [
            completed_set(completedAt='2026-10-11T23:59:59Z', reps=20, goal=20),
            completed_set(completedAt='2026-10-12T00:00:00Z', reps=5, goal=5),
            completed_set(completedAt='2026-10-18T23:59:59Z'),
            completed_set(completedAt='2026-10-19T00:00:00Z', reps=15, goal=15),
        ]
        for record in records:
            self.repository.save(record)
        with patch('backend.history.datetime', wraps=datetime) as clock:
            clock.now.return_value = datetime(2026, 10, 14, tzinfo=timezone.utc)
            # list_workouts only uses datetime.now, so the replacement doesn't affect validation.
            page = self.repository.list_workouts(limit=1, offset=1)
            empty_page = self.repository.list_workouts(limit=1, offset=99)
        self.assertEqual(page['workouts'][0]['id'], records[2]['id'])
        self.assertEqual(page['total'], 4)
        self.assertEqual(page['summary'], {'totalSets': 4, 'totalReps': 50, 'weekReps': 15, 'bestSet': 20})
        self.assertEqual(empty_page['workouts'], [])
        self.assertEqual(empty_page['summary'], page['summary'])

    def test_equal_timestamps_have_stable_order(self):
        records = [completed_set(id=f'00000000-0000-0000-0000-{number:012d}') for number in (1, 3, 2)]
        for record in records:
            self.repository.save(record)
        self.assertEqual(
            [row['id'] for row in self.repository.list_workouts()['workouts']],
            sorted([record['id'] for record in records], reverse=True),
        )

    def test_empty_history_has_zero_summary(self):
        result = self.repository.list_workouts()
        self.assertEqual(result, {
            'workouts': [], 'total': 0,
            'summary': {'totalSets': 0, 'totalReps': 0, 'weekReps': 0, 'bestSet': 0},
        })

    def test_database_constraints_reject_invalid_direct_inserts(self):
        # The database protects its invariants even when Python validation is bypassed.
        for reps, goal, duration in [(0, 5, 1), (10, 11, 1), (9, 10, 1),
                                     (10, 10, -1), (10, 10, float('inf')), (10, 10, float('nan'))]:
            with self.subTest(reps=reps, goal=goal, duration=duration), self.assertRaises(psycopg.errors.CheckViolation):
                with psycopg.connect(self.database_url, connect_timeout=5) as connection:
                    connection.execute('''
                        INSERT INTO workouts (id, completed_at, reps, goal, duration_seconds)
                        VALUES (%s, %s, %s, %s, %s)
                    ''', (uuid4(), datetime.now(timezone.utc), reps, goal, duration))
