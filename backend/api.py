"""Local API. Run with: python -m uvicorn backend.api:app --host 127.0.0.1"""
import asyncio
from contextlib import asynccontextmanager
import json
from urllib.parse import urlparse

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, StrictInt, ValidationError
from starlette.middleware.trustedhost import TrustedHostMiddleware
from typing import Literal
from anyio import CancelScope

from .camera import CameraService


class Command(BaseModel):
    model_config = ConfigDict(extra='forbid')
    command: Literal['start', 'pause', 'stop', 'reset', 'goal']
    goal: StrictInt | None = None
    requestId: StrictInt | None = None


def create_app(service=None):
    service = service if service is not None else CameraService()
    clients = set()
    commands = asyncio.Lock()

    @asynccontextmanager
    async def lifespan(app):
        yield
        await asyncio.to_thread(service.command, 'stop')

    app = FastAPI(title='RepBuddy', lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost', 'testserver'])

    @app.get('/api/health')
    async def health():
        return {'status': 'ok'}

    @app.get('/api/video')
    async def video(request: Request):
        async def frames():
            last_id = -1
            while not await request.is_disconnected():
                frame_id, jpeg = service.latest_frame()
                if jpeg is not None and frame_id != last_id:
                    last_id = frame_id
                    yield (b'--frame\r\nContent-Type: image/jpeg\r\nContent-Length: '
                           + str(len(jpeg)).encode() + b'\r\n\r\n' + jpeg + b'\r\n')
                await asyncio.sleep(1 / 30)
        return StreamingResponse(frames(), media_type='multipart/x-mixed-replace; boundary=frame',
                                 headers={'Cache-Control': 'no-store'})

    @app.websocket('/api/ws')
    async def websocket(ws: WebSocket):
        # Other websites must not be able to start the local webcam.
        origin = ws.headers.get('origin')
        if origin:
            parsed = urlparse(origin)
            if parsed.scheme not in ('http', 'https') or parsed.hostname not in ('localhost', '127.0.0.1'):
                await ws.close(code=1008)
                return
        await ws.accept()
        clients.add(ws)
        command_error = None
        ack_id = None

        async def receive_commands():
            nonlocal command_error, ack_id
            while True:
                raw = await ws.receive_text()
                request_id = None
                try:
                    if len(raw) > 1024:
                        raise ValueError('Command is too large.')
                    message = Command.model_validate(json.loads(raw))
                    request_id = message.requestId
                    async with commands:
                        await asyncio.to_thread(service.command, message.command, message.goal)
                    command_error = None
                except (ValidationError, ValueError) as exc:
                    command_error = ('Invalid workout command.' if isinstance(exc, ValidationError)
                                     else str(exc))
                ack_id = request_id

        receiver = asyncio.create_task(receive_commands())
        try:
            while not receiver.done():
                await ws.send_json({'type': 'status', **service.snapshot(),
                                    'commandError': command_error, 'ackId': ack_id})
                await asyncio.sleep(0.1)
            await receiver
        except (WebSocketDisconnect, OSError):
            pass
        finally:
            clients.discard(ws)
            # Disconnect may cancel this handler; still release its resources.
            with CancelScope(shield=True):
                receiver.cancel()
                await asyncio.gather(receiver, return_exceptions=True)
                async with commands:
                    if not clients:
                        await asyncio.to_thread(service.command, 'stop')

    return app


app = create_app()
