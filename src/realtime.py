from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
from dataclasses import dataclass

from fastapi import WebSocket
from websockets.asyncio.client import ClientConnection, connect

from .config import Settings
from .prompt import build_initial_greeting, build_session_update

logger = logging.getLogger("hpg.voice.realtime")


def safe_call_ref(call_control_id: str | None) -> str:
    if not call_control_id:
        return "unknown"
    return hashlib.sha256(call_control_id.encode("utf-8")).hexdigest()[:12]


@dataclass
class PlaybackState:
    item_id: str | None = None
    generated_ms: int = 0
    played_ms: int = 0

    def reset(self, item_id: str | None = None) -> None:
        self.item_id = item_id
        self.generated_ms = 0
        self.played_ms = 0


class RealtimeBridge:
    def __init__(self, telnyx_ws: WebSocket, settings: Settings):
        self.telnyx_ws = telnyx_ws
        self.settings = settings
        self.openai_ws: ClientConnection | None = None
        self.stream_id: str | None = None
        self.call_ref = "unknown"
        self.playback = PlaybackState()
        self._greeting_sent = False

    async def run(self) -> None:
        try:
            async with connect(
                self.settings.openai_realtime_url,
                additional_headers={
                    "Authorization": f"Bearer {self.settings.openai_api_key}",
                    "OpenAI-Safety-Identifier": "hpg-voice-test-caller",
                },
                ping_interval=20,
                ping_timeout=20,
                max_size=None,
            ) as openai_ws:
                self.openai_ws = openai_ws
                await self._send_openai(
                    build_session_update(
                        self.settings.openai_realtime_model,
                        self.settings.openai_realtime_voice,
                    )
                )
                await self._relay_both_directions()
        finally:
            self.openai_ws = None
            logger.info("media bridge closed call_ref=%s", self.call_ref)

    async def _relay_both_directions(self) -> None:
        to_openai = asyncio.create_task(self._telnyx_to_openai())
        to_telnyx = asyncio.create_task(self._openai_to_telnyx())
        done, pending = await asyncio.wait(
            {to_openai, to_telnyx}, return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            task.result()

    async def _telnyx_to_openai(self) -> None:
        while True:
            raw = await self.telnyx_ws.receive_text()
            event = json.loads(raw)
            event_type = event.get("event")

            if event_type == "start":
                self.stream_id = event.get("stream_id")
                start = event.get("start") or {}
                self.call_ref = safe_call_ref(start.get("call_control_id"))
                media_format = start.get("media_format") or {}
                if str(media_format.get("encoding", "")).upper() != "PCMU":
                    raise RuntimeError("Telnyx stream must use PCMU")
                logger.info("media stream started call_ref=%s", self.call_ref)
            elif event_type == "media":
                media = event.get("media") or {}
                if media.get("track") not in (None, "inbound", "inbound_track"):
                    continue
                payload = media.get("payload")
                if payload:
                    await self._send_openai(
                        {"type": "input_audio_buffer.append", "audio": payload}
                    )
            elif event_type == "mark":
                name = str((event.get("mark") or {}).get("name", ""))
                self._acknowledge_mark(name)
            elif event_type in ("stop", "error"):
                return

    async def _openai_to_telnyx(self) -> None:
        assert self.openai_ws is not None
        async for raw in self.openai_ws:
            event = json.loads(raw)
            event_type = event.get("type")

            if event_type == "session.updated" and not self._greeting_sent:
                self._greeting_sent = True
                await self._send_openai(build_initial_greeting())
            elif event_type == "response.output_item.added":
                item = event.get("item") or {}
                if item.get("role") == "assistant":
                    self.playback.reset(item.get("id"))
            elif event_type == "response.output_audio.delta":
                await self._send_audio_delta(event.get("delta"))
            elif event_type == "input_audio_buffer.speech_started":
                await self._handle_interruption()
            elif event_type == "error":
                error = event.get("error") or {}
                logger.error(
                    "OpenAI Realtime error call_ref=%s type=%s code=%s",
                    self.call_ref,
                    error.get("type"),
                    error.get("code"),
                )

    async def _send_audio_delta(self, payload: str | None) -> None:
        if not payload:
            return
        await self.telnyx_ws.send_text(
            json.dumps({"event": "media", "media": {"payload": payload}})
        )
        try:
            audio_bytes = len(base64.b64decode(payload, validate=True))
        except ValueError:
            return
        self.playback.generated_ms += audio_bytes // 8  # PCMU: 8 bytes per ms.
        if self.playback.item_id:
            name = f"hpg:{self.playback.item_id}:{self.playback.generated_ms}"
            await self.telnyx_ws.send_text(
                json.dumps({"event": "mark", "mark": {"name": name}})
            )

    def _acknowledge_mark(self, name: str) -> None:
        parts = name.split(":", 2)
        if len(parts) != 3 or parts[0] != "hpg":
            return
        item_id, milliseconds = parts[1], parts[2]
        if item_id != self.playback.item_id:
            return
        try:
            self.playback.played_ms = max(self.playback.played_ms, int(milliseconds))
        except ValueError:
            return

    async def _handle_interruption(self) -> None:
        await self.telnyx_ws.send_text(json.dumps({"event": "clear"}))
        if self.playback.item_id and self.playback.played_ms > 0:
            await self._send_openai(
                {
                    "type": "conversation.item.truncate",
                    "item_id": self.playback.item_id,
                    "content_index": 0,
                    "audio_end_ms": self.playback.played_ms,
                }
            )
        self.playback.reset()

    async def _send_openai(self, event: dict) -> None:
        if self.openai_ws is None:
            raise RuntimeError("OpenAI Realtime socket is not connected")
        await self.openai_ws.send(json.dumps(event))

