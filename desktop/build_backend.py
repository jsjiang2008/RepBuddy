"""Build the Python runtime and collect only distributable desktop resources."""
import importlib.metadata
import os
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
RESOURCES = ROOT / 'build' / 'desktop-resources'


def main():
    if sys.platform != 'win32':
        raise SystemExit('Build the Windows installer on Windows with Python 3.11.')
    postgres = Path(os.environ.get('REPBUDDY_POSTGRES_HOME', r'C:\Program Files\PostgreSQL\18'))
    for executable in ('postgres.exe', 'initdb.exe', 'pg_ctl.exe'):
        if not (postgres / 'bin' / executable).is_file():
            raise SystemExit('Install PostgreSQL 18 or set REPBUDDY_POSTGRES_HOME to its installation folder.')
    if not (ROOT / 'frontend' / 'dist' / 'index.html').is_file():
        raise SystemExit('Build the frontend before packaging the tracker.')
    RESOURCES.mkdir(parents=True, exist_ok=True)
    # Copy programs and their licences, never installed databases or local settings.
    for folder in ('bin', 'lib', 'share', 'doc'):
        shutil.copytree(postgres / folder, RESOURCES / 'postgres' / folder, dirs_exist_ok=True)
    for license_file in postgres.glob('*license*.txt'):
        shutil.copy2(license_file, RESOURCES / 'postgres' / license_file.name)
    shutil.copytree(ROOT / 'frontend' / 'dist', RESOURCES / 'frontend', dirs_exist_ok=True)

    # Preserve dependency notices alongside the distributed runtime.
    notices = RESOURCES / 'licenses'
    notices.mkdir(exist_ok=True)
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata['Name']
        for entry in distribution.files or []:
            if any(part.lower().startswith(('license', 'copying', 'notice')) for part in entry.parts):
                source = Path(str(distribution.locate_file(entry)))
                if source.is_file():
                    target = notices / name / str(entry).replace('..', '_')
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)

    # Include model data and dynamic imports used by the camera and web server.
    command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--onedir',
               '--name', 'repbuddy-tracker', '--distpath', str(ROOT / 'build' / 'python-dist'),
               '--workpath', str(ROOT / 'build' / 'pyinstaller'), '--specpath', str(ROOT / 'build'),
               '--paths', str(ROOT), '--add-data', f'{ROOT / "backend" / "migrations"};backend/migrations',
               '--collect-data', 'mediapipe', '--collect-binaries', 'mediapipe',
               '--collect-all', 'cv2_enumerate_cameras', '--collect-all', 'psycopg_binary',
               '--collect-submodules', 'uvicorn', '--hidden-import', 'backend.vision',
               '--hidden-import', 'uvicorn.logging', '--hidden-import', 'websockets.legacy.server']
    for excluded in ('torch', 'tensorflow', 'jax', 'jaxlib', 'pytest', 'IPython', 'tkinter'):
        command.extend(['--exclude-module', excluded])
    command.append(str(ROOT / 'backend' / 'desktop.py'))
    subprocess.run(command, cwd=ROOT, check=True, env={**os.environ, 'MPLBACKEND': 'Agg'})
    shutil.copytree(ROOT / 'build' / 'python-dist' / 'repbuddy-tracker', RESOURCES / 'tracker', dirs_exist_ok=True)
    print('Desktop resources are ready. No development credentials or workout data were copied.')


if __name__ == '__main__':
    main()
