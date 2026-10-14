"""Local API. Run with: python -m uvicorn backend.api:app --host 127.0.0.1"""
import asyncio
from contextlib import asynccontextmanager
import json
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Query, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, StrictInt, ValidationError
from starlette.middleware.trustedhost import TrustedHostMiddleware
from typing import Literal
from anyio import CancelScope

from .camera import CameraService
from .history import HistoryRepository


class Command(BaseModel):
    model_config = ConfigDict(extra='forbid')
    command: Literal['start', 'pause', 'stop', 'reset', 'goal', 'camera', 'retrySave']
    goal: StrictInt | None = None
    cameraIndex: StrictInt | None = None
    requestId: StrictInt | None = None


def create_app(service=None, history=None):
    history = history if history is not None else HistoryRepository()
    service = service if service is not None else CameraService(on_completed=history.save)
    clients = set()
    commands = asyncio.Lock()

    @asynccontextmanager
    async def lifespan(app):
        try:
            await asyncio.to_thread(history.initialize)
        except Exception:
            raise RuntimeError('Could not connect to PostgreSQL. Start your PostgreSQL server and check DATABASE_URL in .env.') from None
        try:
            yield
        finally:
            await asyncio.to_thread(service.close)

    app = FastAPI(title='RepBuddy', lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost', 'testserver'])

    @app.get('/api/health')
    async def health():
        try:
            await asyncio.to_thread(history.check)
        except Exception:
            raise HTTPException(503, 'PostgreSQL is unavailable.') from None
        return {'status': 'ok'}

    @app.get('/api/cameras')
    async def cameras(response: Response):
        response.headers['Cache-Control'] = 'no-store'
        try:
            return await asyncio.to_thread(service.list_cameras)
        except Exception:
            raise HTTPException(503, 'Could not list webcams. Check the camera connection and try Refresh.') from None

    @app.get('/api/history')
    async def workouts(response: Response, limit: int = Query(20, ge=1, le=100),
                       offset: int = Query(0, ge=0, le=1_000_000)):
        response.headers['Cache-Control'] = 'no-store'
        try:
            return await asyncio.to_thread(history.list_workouts, limit, offset)
        except Exception:
            raise HTTPException(503, 'Workout history is unavailable. Check PostgreSQL and try again.') from None

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
                        if message.command == 'camera':
                            if message.cameraIndex is None:
                                raise ValueError('Choose a webcam first.')
                            await asyncio.to_thread(service.command, 'camera', camera_index=message.cameraIndex)
                        else:
                            await asyncio.to_thread(service.command, message.command, message.goal)
                    command_error = None
                except (ValidationError, ValueError) as exc:
                    command_error = ('Invalid workout command.' if isinstance(exc, ValidationError)
                                     else str(exc))
                except RuntimeError:
                    command_error = 'Could not complete that command. Check the camera connection and try again.'
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
