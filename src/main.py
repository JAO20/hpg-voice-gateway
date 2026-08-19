from __future__ import annotations

import json
import logging
from collections import deque
from contextlib import asynccontextmanager

import uvicorn
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, WebSocket
from fastapi.responses import JSONResponse

from .config import Settings
from .realtime import RealtimeBridge, safe_call_ref
from .security import stream_token_matches, verify_telnyx_signature
from .telnyx_api import TelnyxAPIError, answer_call

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("hpg.voice")
settings = Settings.from_env()


@asynccontextmanager
async def lifespan(_: FastAPI):
    missing = settings.missing_runtime_values()
    if missing:
        logger.warning("gateway not call-ready; missing variables=%s", ",".join(missing))
    yield


app = FastAPI(title="HPG Voice Gateway", version="0.1.0", lifespan=lifespan)

_recent_event_ids: deque[str] = deque(maxlen=1000)
_recent_event_id_set: set[str] = set()


def _remember_event(event_id: str) -> bool:
    """Return False for a duplicate. Command IDs provide downstream idempotency too."""
    if event_id in _recent_event_id_set:
        return False
    if len(_recent_event_ids) == _recent_event_ids.maxlen:
        evicted = _recent_event_ids.popleft()
        _recent_event_id_set.discard(evicted)
    _recent_event_ids.append(event_id)
    _recent_event_id_set.add(event_id)
    return True


@app.get("/healthz")
async def healthz() -> dict:
    missing = settings.missing_runtime_values()
    return {
        "status": "ok" if not missing else "configuration_required",
        "service": "hpg-voice-gateway",
        "version": app.version,
        "missing_variables": missing,
    }


async def _answer_incoming_call(call_control_id: str, event_id: str) -> None:
    try:
        await answer_call(
            call_control_id,
            api_key=settings.telnyx_api_key,
            stream_url=settings.media_stream_url,
            stream_auth_token=settings.telnyx_stream_auth_token,
            command_id=event_id,
        )
        logger.info("incoming call answered call_ref=%s", safe_call_ref(call_control_id))
    except TelnyxAPIError as exc:
        logger.error(
            "failed to answer incoming call call_ref=%s error=%s",
            safe_call_ref(call_control_id),
            str(exc),
        )


@app.post("/telnyx/webhooks")
async def telnyx_webhook(request: Request, background_tasks: BackgroundTasks):
    raw_body = await request.body()
    signature = request.headers.get("telnyx-signature-ed25519", "")
    timestamp = request.headers.get("telnyx-timestamp", "")
    if not verify_telnyx_signature(
        raw_body, signature, timestamp, settings.telnyx_public_key
    ):
        raise HTTPException(status_code=403, detail="Invalid Telnyx signature")

    try:
        envelope = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON") from exc

    data = envelope.get("data") or {}
    event_id = str(data.get("id") or "")
    event_type = str(data.get("event_type") or "")
    payload = data.get("payload") or {}
    if not event_id:
        raise HTTPException(status_code=400, detail="Missing event id")
    if not _remember_event(event_id):
        return JSONResponse({"received": True, "duplicate": True})

    if event_type == "call.initiated" and payload.get("direction") == "incoming":
        call_control_id = payload.get("call_control_id")
        if call_control_id:
            background_tasks.add_task(
                _answer_incoming_call, str(call_control_id), event_id
            )

    return JSONResponse({"received": True})


@app.websocket("/telnyx/media")
async def telnyx_media(websocket: WebSocket) -> None:
    auth = (
        websocket.headers.get("x-telnyx-streaming-auth-token")
        or websocket.headers.get("authorization")
    )
    if not stream_token_matches(auth, settings.telnyx_stream_auth_token):
        await websocket.close(code=1008, reason="Unauthorized media stream")
        return
    await websocket.accept()
    bridge = RealtimeBridge(websocket, settings)
    try:
        await bridge.run()
    except Exception as exc:
        logger.exception("media bridge failed error_type=%s", type(exc).__name__)
        await websocket.close(code=1011, reason="Media bridge failure")


if __name__ == "__main__":
    uvicorn.run("src.main:app", host="0.0.0.0", port=settings.port)
