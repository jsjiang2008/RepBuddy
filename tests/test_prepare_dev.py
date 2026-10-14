"""Startup must never require or launch Docker unless the user requests it."""
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import unittest
from unittest.mock import patch

from backend import prepare_dev
from backend.history import DEFAULT_DATABASE_URL


class PrepareDevTests(unittest.TestCase):
    def setUp(self):
        self.output = StringIO()
        self.enterContext(redirect_stdout(self.output))
        self.repository = self.enterContext(patch.object(prepare_dev, 'HistoryRepository'))
        self.repository.return_value.database_url = DEFAULT_DATABASE_URL
        self.which = self.enterContext(patch.object(prepare_dev.shutil, 'which', return_value='docker.exe'))
        self.run = self.enterContext(patch.object(prepare_dev.subprocess, 'run'))
        self.run.return_value.returncode = 0
        self.migrate = self.enterContext(patch.object(prepare_dev, 'migrate', return_value=0))

    def test_default_startup_only_prepares_configured_postgresql(self):
        self.assertEqual(prepare_dev.main([]), 0)
        self.migrate.assert_called_once_with()
        self.repository.assert_not_called()
        self.which.assert_not_called()
        self.run.assert_not_called()

    def test_default_startup_propagates_database_failure_without_trying_docker(self):
        self.migrate.return_value = 1
        self.assertEqual(prepare_dev.main([]), 1)
        self.which.assert_not_called()
        self.run.assert_not_called()

    def test_explicit_docker_startup_prepares_database_after_compose(self):
        events = []
        self.run.side_effect = lambda *args, **kwargs: events.append('compose') or self.run.return_value
        self.migrate.side_effect = lambda: events.append('migrate') or 0
        self.assertEqual(prepare_dev.main(['--docker']), 0)
        self.run.assert_called_once_with(
            ['docker.exe', 'compose', 'up', '-d', '--wait', '--wait-timeout', '60', 'db'],
            cwd=Path(prepare_dev.__file__).resolve().parents[1], check=False,
        )
        self.assertEqual(events, ['compose', 'migrate'])

    def test_docker_mode_rejects_a_different_database(self):
        self.repository.return_value.database_url = 'postgresql://private-password@localhost/native'
        self.assertEqual(prepare_dev.main(['--docker']), 1)
        self.which.assert_not_called()
        self.run.assert_not_called()
        self.migrate.assert_not_called()
        self.assertIn('DATABASE_URL points to another PostgreSQL server', self.output.getvalue())
        self.assertNotIn('private-password', self.output.getvalue())

    def test_missing_docker_skips_migrations(self):
        self.which.return_value = None
        self.assertEqual(prepare_dev.main(['--docker']), 1)
        self.run.assert_not_called()
        self.migrate.assert_not_called()

    def test_failed_compose_skips_migrations(self):
        self.run.return_value.returncode = 1
        self.assertEqual(prepare_dev.main(['--docker']), 1)
        self.migrate.assert_not_called()

    def test_docker_launch_error_skips_migrations(self):
        self.run.side_effect = OSError('could not launch')
        self.assertEqual(prepare_dev.main(['--docker']), 1)
        self.migrate.assert_not_called()

    def test_interrupted_docker_startup_skips_migrations(self):
        self.run.side_effect = KeyboardInterrupt
        self.assertEqual(prepare_dev.main(['--docker']), 130)
        self.migrate.assert_not_called()
