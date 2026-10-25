"""Check repeatable desktop builds without running packaging tools."""
from contextlib import ExitStack
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from desktop import build_backend


class DesktopBuildTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.resources = self.root / 'build' / 'desktop-resources'
        self.resources.mkdir(parents=True)
        (self.resources / 'old-file.txt').write_text('previous build')
        self.postgres = self.root / 'postgres'
        for folder in ('bin', 'lib', 'share', 'doc'):
            (self.postgres / folder).mkdir(parents=True)
        for name in ('postgres.exe', 'initdb.exe', 'pg_ctl.exe'):
            (self.postgres / 'bin' / name).write_bytes(b'postgres fixture')
        frontend = self.root / 'frontend' / 'dist'
        frontend.mkdir(parents=True)
        (frontend / 'index.html').write_text('current interface')
        tracker = self.root / 'build' / 'python-dist' / 'repbuddy-tracker'
        tracker.mkdir(parents=True)
        (tracker / 'repbuddy-tracker.exe').write_bytes(b'tracker fixture')
        self.stack.enter_context(patch.object(build_backend, 'ROOT', self.root))
        self.stack.enter_context(patch.object(build_backend, 'RESOURCES', self.resources))
        self.stack.enter_context(patch.dict(os.environ, REPBUDDY_POSTGRES_HOME=str(self.postgres)))
        self.stack.enter_context(patch.object(build_backend.sys, 'platform', 'win32'))
        self.stack.enter_context(patch.object(build_backend.importlib.metadata, 'distributions', return_value=[]))
        self.package = self.stack.enter_context(patch.object(build_backend.subprocess, 'run'))

    def test_rebuild_removes_stale_files_and_keeps_current_resources(self):
        build_backend.main()
        self.assertFalse((self.resources / 'old-file.txt').exists())
        self.assertEqual((self.resources / 'frontend' / 'index.html').read_text(), 'current interface')
        self.assertTrue((self.resources / 'tracker' / 'repbuddy-tracker.exe').is_file())
        self.assertTrue((self.resources / 'postgres' / 'bin' / 'postgres.exe').is_file())
        self.assertEqual(list((self.root / 'build').glob('desktop-stage-*')), [])

    def test_failed_collection_preserves_the_previous_build(self):
        # A missing runtime file must not discard the last usable resources.
        (self.postgres / 'lib').rmdir()
        with self.assertRaises(FileNotFoundError):
            build_backend.main()
        self.assertEqual((self.resources / 'old-file.txt').read_text(), 'previous build')
        self.assertEqual(list((self.root / 'build').glob('desktop-stage-*')), [])

    def test_output_outside_build_resources_is_rejected(self):
        with patch.object(build_backend, 'RESOURCES', self.root):
            with self.assertRaises(ValueError):
                build_backend.main()
        self.package.assert_not_called()
        self.assertTrue((self.resources / 'old-file.txt').exists())
