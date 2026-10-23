"""Store completed sets in PostgreSQL. Camera images are never stored here."""
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import math
import os
from pathlib import Path
from typing import Any, LiteralString, cast
from uuid import UUID

from dotenv import load_dotenv
import psycopg
from psycopg.rows import dict_row


# Find saved settings and database setup files relative to this project.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = Path(__file__).with_name('migrations')
DEFAULT_DATABASE_URL = 'postgresql://repbuddy:repbuddy_local@127.0.0.1:5433/repbuddy'
MIGRATION_LOCK = 8243560241


def _validated_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """Reject incomplete or invalid workout results before opening the database."""
    # Each completed set has a unique identifier so retries cannot create duplicates.
    try:
        workout_id = UUID(str(record['id']))
    except (KeyError, ValueError, TypeError, AttributeError) as error:
        raise ValueError('A completed set needs a valid UUID.') from error

    reps, goal = record.get('reps'), record.get('goal')
    # Only supported goals and fully completed sets may be saved.
    if type(goal) is not int or goal not in (5, 10, 15, 20):
        raise ValueError('The completed set has an invalid rep goal.')
    if type(reps) is not int or reps != goal:
        raise ValueError('Only sets that reach their rep goal can be saved.')

    duration = record.get('durationSeconds')
    # Reject missing durations and numbers that are negative or infinite.
    if isinstance(duration, bool) or not isinstance(duration, (int, float)):
        raise ValueError('The set duration must be a finite, nonnegative number.')
    try:
        duration = float(duration)
    except OverflowError as error:
        raise ValueError('The set duration must be a finite, nonnegative number.') from error
    if not math.isfinite(duration) or duration < 0:
        raise ValueError('The set duration must be a finite, nonnegative number.')

    completed_at = record.get('completedAt')
    # Store a timezone with every date so history works across different timezones.
    if isinstance(completed_at, str):
        try:
            completed_at = datetime.fromisoformat(completed_at.replace('Z', '+00:00'))
        except ValueError as error:
            raise ValueError('The completion time must be a valid ISO timestamp.') from error
    if not isinstance(completed_at, datetime) or completed_at.utcoffset() is None:
        raise ValueError('The completion time must include a timezone.')

    return {
        'id': workout_id,
        'completed_at': completed_at.astimezone(timezone.utc),
        'reps': reps,
        'goal': goal,
        'duration_seconds': duration,
    }


class HistoryRepository:
    """Read and write workout history using a separate connection for each operation."""

    def __init__(self, database_url: str | None = None):
        # Explicit settings take priority over the local settings file and fallback.
        load_dotenv(PROJECT_ROOT / '.env', override=False)
        self.database_url = database_url or os.environ.get('DATABASE_URL') or DEFAULT_DATABASE_URL

    @contextmanager
    def _connection(self, *, read_only: bool = False) -> Iterator[psycopg.Connection[dict[str, Any]]]:
        # Close the connection automatically and undo unfinished writes after errors.
        # Connections and lock waits are bounded even when the local database is down.
        with psycopg.Connection[dict[str, Any]].connect(
            self.database_url, connect_timeout=5, row_factory=dict_row
        ) as connection:
            if read_only:
                # Keep totals and records consistent while other threads save workouts.
                connection.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
                connection.read_only = True
            connection.execute(
                "SELECT set_config('statement_timeout', '5000', true), "
                "set_config('lock_timeout', '5000', true)"
            )
            yield connection

    def initialize(self) -> None:
        """Apply each database setup file once, even if two servers start together."""
        migrations = sorted(MIGRATIONS_DIR.glob('[0-9][0-9][0-9]_*.sql'))
        if not migrations:
            raise RuntimeError('No database migrations were found.')
        with self._connection() as connection:
            # A database lock lets only one startup process change the tables at a time.
            connection.execute('SELECT pg_advisory_xact_lock(%s)', (MIGRATION_LOCK,))
            connection.execute('''
                CREATE TABLE IF NOT EXISTS repbuddy_schema_migrations (
                    version TEXT PRIMARY KEY,
                    checksum TEXT NOT NULL,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            applied = {
                row['version']: row['checksum']
                for row in connection.execute('SELECT version, checksum FROM repbuddy_schema_migrations')
            }
            for migration in migrations:
                # Compare saved file fingerprints to catch changes to an applied migration.
                sql = migration.read_text(encoding='utf-8')
                checksum = hashlib.sha256(sql.encode('utf-8')).hexdigest()
                version = migration.name.split('_', 1)[0]
                if version in applied:
                    if applied[version] != checksum:
                        raise RuntimeError(f'Database migration {version} changed after it was applied.')
                    continue
                # This SQL comes from project migration files, never from user input.
                connection.execute(cast(LiteralString, sql))
                connection.execute(
                    'INSERT INTO repbuddy_schema_migrations (version, checksum) VALUES (%s, %s)',
                    (version, checksum),
                )
                applied[version] = checksum

    def check(self) -> bool:
        """Check that the database and workout table can be reached."""
        with self._connection(read_only=True) as connection:
            connection.execute('SELECT id FROM workouts LIMIT 0')
        return True

    def save(self, record: Mapping[str, Any]) -> bool:
        # Insert a finished set, or leave an already saved copy unchanged.
        values = _validated_record(record)
        with self._connection() as connection:
            inserted = connection.execute('''
                INSERT INTO workouts (id, completed_at, reps, goal, duration_seconds)
                VALUES (%(id)s, %(completed_at)s, %(reps)s, %(goal)s, %(duration_seconds)s)
                ON CONFLICT (id) DO NOTHING
                RETURNING id
            ''', values).fetchone()
        return inserted is not None

    def list_workouts(self, limit: int = 20, offset: int = 0) -> dict[str, Any]:
        # Return one page of recent workouts and totals across the whole history.
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError('The history page size must be between 1 and 100.')
        if type(offset) is not int or offset < 0:
            raise ValueError('The history offset must be zero or greater.')
        now = datetime.now(timezone.utc)
        # Weekly totals start at midnight on Monday using universal time.
        week_start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        week_end = week_start + timedelta(days=7)
        # A consistent snapshot keeps pagination totals and summaries in sync with rows.
        with self._connection(read_only=True) as connection:
            summary = connection.execute('''
                SELECT COUNT(*) AS total_sets,
                    COALESCE(SUM(reps), 0) AS total_reps,
                    COALESCE(SUM(reps) FILTER (
                        WHERE completed_at >= %s AND completed_at < %s
                    ), 0) AS week_reps,
                    COALESCE(MAX(reps), 0) AS best_set
                FROM workouts
            ''', (week_start, week_end)).fetchone()
            rows = connection.execute('''
                SELECT id, completed_at, reps, goal, duration_seconds
                FROM workouts
                ORDER BY completed_at DESC, id DESC
                LIMIT %s OFFSET %s
            ''', (limit, offset)).fetchall()
        assert summary is not None
        # Convert database values into ordinary numbers and strings for the frontend.
        return {
            'workouts': [{
                'id': str(row['id']),
                'completedAt': row['completed_at'].astimezone(timezone.utc).isoformat().replace('+00:00', 'Z'),
                'reps': row['reps'],
                'goal': row['goal'],
                'durationSeconds': row['duration_seconds'],
            } for row in rows],
            'total': summary['total_sets'],
            'summary': {
                'totalSets': summary['total_sets'],
                'totalReps': summary['total_reps'],
                'weekReps': summary['week_reps'],
                'bestSet': summary['best_set'],
            },
        }


def main() -> int:
    # This entry point prepares the database when called from the terminal.
    try:
        repository = HistoryRepository()
        repository.initialize()
        repository.check()
    except (psycopg.Error, RuntimeError, OSError):
        # Show a useful error without exposing private database connection details.
        print('Workout database is unavailable. Start PostgreSQL and check DATABASE_URL in .env.')
        return 1
    print('Workout database is ready. Migrations are up to date.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
