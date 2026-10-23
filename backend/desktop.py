"""Serve the packaged interface and tracker until Electron closes its input pipe."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import secrets
import socket
import sys
import threading

import uvicorn
from fastapi.staticfiles import StaticFiles

from backend.desktop_database import DesktopDatabase


class DesktopAccess:
    def __init__(self, app, token):
        self.app = app
        self.token = token

    async def __call__(self, scope, receive, send):
        # Only the Electron session can reach the private local server.
        if scope['type'] in ('http', 'websocket'):
            supplied = dict(scope.get('headers', [])).get(b'x-repbuddy-token', b'')
            if not secrets.compare_digest(supplied, self.token.encode()):
                if scope['type'] == 'websocket':
                    await send({'type': 'websocket.close', 'code': 1008})
                else:
                    await send({'type': 'http.response.start', 'status': 403, 'headers': []})
                    await send({'type': 'http.response.body', 'body': b'Forbidden'})
                return
        await self.app(scope, receive, send)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--resources', type=Path, required=True)
    parser.add_argument('--check-model', action='store_true')
    args = parser.parse_args()
    token = os.environ.pop('REPBUDDY_DESKTOP_TOKEN', '')
    if len(token) < 32:
        raise RuntimeError('Desktop startup requires a private session token.')
    # Installed apps never read development credentials from the working folder.
    os.environ['PYTHON_DOTENV_DISABLED'] = '1'
    from backend.api import create_app
    from backend.history import HistoryRepository

    database = DesktopDatabase(args.resources / 'postgres', args.data_dir)
    stopped = threading.Event()

    def watch_parent():
        # Closing the parent pipe also handles an Electron crash.
        sys.stdin.buffer.read()
        stopped.set()

    threading.Thread(target=watch_parent, daemon=True).start()
    try:
        database_url = database.start()
        if stopped.is_set():
            return
        if args.check_model:
            # Check bundled model files without opening the webcam.
            import numpy as np
            from backend.vision import PoseProcessor
            processor = PoseProcessor()
            try:
                processor.process(np.zeros((480, 640, 3), dtype=np.uint8))
            finally:
                processor.close()
        application = create_app(history=HistoryRepository(database_url))
        application.mount('/', StaticFiles(directory=args.resources / 'frontend', html=True), name='frontend')
        protected = DesktopAccess(application, token)
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen(128)
            server = uvicorn.Server(uvicorn.Config(protected, log_level='warning', access_log=False,
                                                   timeout_graceful_shutdown=10))

            async def serve():
                task = asyncio.create_task(server.serve(sockets=[listener]))
                while not server.started and not task.done() and not stopped.is_set():
                    await asyncio.sleep(0.05)
                if server.started and not stopped.is_set():
                    print(json.dumps({'event': 'ready', 'port': listener.getsockname()[1]}), flush=True)
                while not task.done() and not stopped.is_set():
                    await asyncio.sleep(0.1)
                server.should_exit = True
                await task

            asyncio.run(serve())
    finally:
        database.close()


if __name__ == '__main__':
    main()
