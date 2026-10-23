"""Prepare PostgreSQL, starting Docker only when explicitly requested."""
import argparse
from pathlib import Path
import shutil
import subprocess

from .history import DEFAULT_DATABASE_URL, HistoryRepository, main as migrate


def main(argv: list[str] | None = None) -> int:
    # Read the optional Docker setting from the terminal command.
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--docker', action='store_true', help='Start the bundled PostgreSQL Docker service.')
    args = parser.parse_args(argv)

    if args.docker:
        # Only start Docker when requested and when its bundled database is selected.
        repository = HistoryRepository()
        if repository.database_url != DEFAULT_DATABASE_URL:
            print('DATABASE_URL points to another PostgreSQL server. Use npm run dev, '
                  'or configure the bundled Docker database URL before using npm run dev:docker.')
            return 1
        docker = shutil.which('docker')
        if docker is None:
            print('Docker was requested but is not installed. Install and start Docker Desktop, '
                  'or use npm run dev with your PostgreSQL server.')
            return 1
        print('Starting the local workout database...', flush=True)
        # Wait for the database container to be ready before starting the app.
        try:
            result = subprocess.run(
                [docker, 'compose', 'up', '-d', '--wait', '--wait-timeout', '60', 'db'],
                cwd=Path(__file__).resolve().parents[1], check=False,
            )
        except KeyboardInterrupt:
            return 130
        except OSError:
            print('Could not launch Docker. Check your Docker installation and try again.')
            return 1
        if result.returncode:
            print('Could not start PostgreSQL. Open Docker Desktop and try npm run dev:docker again.')
            return 1
    # Normal startup connects directly to PostgreSQL and applies pending table changes.
    return migrate()


if __name__ == '__main__':
    raise SystemExit(main())
