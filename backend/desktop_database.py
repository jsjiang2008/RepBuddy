"""Run the bundled PostgreSQL server for this desktop user only."""
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import tempfile

import psycopg
from psycopg.conninfo import make_conninfo


class DesktopDatabase:
    def __init__(self, binaries: Path, data_dir: Path):
        self.bin = binaries / 'bin'
        self.root = data_dir
        self.cluster = data_dir / 'postgres-18'
        self.started = False

    def _run(self, program, *args, check=True):
        # Hide utility windows and never print the database password.
        # A file avoids waiting for a pipe inherited by the long running server.
        with tempfile.TemporaryFile() as output:
            result = subprocess.run(
                [str(self.bin / f'{program}.exe'), *map(str, args)],
                stdout=output, stderr=subprocess.STDOUT, timeout=120,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), check=False,
            )
            output.seek(0)
            result = subprocess.CompletedProcess(result.args, result.returncode,
                                                 output.read().decode('utf-8', errors='replace'))
            if check:
                result.check_returncode()
            return result

    def start(self):
        self.root.mkdir(parents=True, exist_ok=True)
        settings_path = self.root / 'database.json'
        if settings_path.exists():
            settings = json.loads(settings_path.read_text(encoding='utf-8'))
        else:
            if self.cluster.exists():
                raise RuntimeError('Database settings are missing. Restore database.json from your backup.')
            settings = {'password': secrets.token_urlsafe(32)}
            # Exclusive creation avoids overwriting existing credentials.
            with settings_path.open('x', encoding='utf-8') as file:
                json.dump(settings, file)
            os.chmod(settings_path, 0o600)

        if not self.cluster.exists():
            # Build a new cluster separately so an interrupted setup can be retried.
            with tempfile.TemporaryDirectory(prefix='database-setup-', dir=self.root) as temporary:
                staging = Path(temporary)
                password_file = staging / 'password.txt'
                password_file.write_text(settings['password'], encoding='utf-8')
                self._run('initdb', '-D', staging / 'cluster', '--username=repbuddy',
                          '--auth=scram-sha-256', '--encoding=UTF8', '--locale=C',
                          f'--pwfile={password_file}')
                (staging / 'cluster').rename(self.cluster)
        if (self.cluster / 'PG_VERSION').read_text().strip() != '18':
            raise RuntimeError('This database needs a PostgreSQL upgrade before it can be opened.')

        # Recover only the private app database after an interrupted app shutdown.
        if self._run('pg_ctl', '-D', self.cluster, 'status', check=False).returncode == 0:
            self._run('pg_ctl', '-D', self.cluster, '-m', 'fast', '-w', '-t', '30', 'stop')
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1', 0))
            port = reservation.getsockname()[1]
        self._run('pg_ctl', '-D', self.cluster, '-l', self.root / 'postgres.log',
                  '-o', f'-h 127.0.0.1 -p {port} -c max_connections=20 -c shared_buffers=32MB',
                  '-w', '-t', '45', 'start')
        self.started = True
        connection_url = make_conninfo(host='127.0.0.1', port=port, user='repbuddy',
                                      password=settings['password'], dbname='postgres')
        with psycopg.connect(connection_url, autocommit=True, connect_timeout=5) as connection:
            exists = connection.execute("SELECT 1 FROM pg_database WHERE datname = 'repbuddy'").fetchone()
            if exists is None:
                connection.execute('CREATE DATABASE repbuddy')
        return make_conninfo(connection_url, dbname='repbuddy')

    def close(self):
        # The app owns this cluster and never stops a system PostgreSQL service.
        if self.started:
            self._run('pg_ctl', '-D', self.cluster, '-m', 'fast', '-w', '-t', '30', 'stop')
            self.started = False
