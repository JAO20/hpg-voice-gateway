from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from websockets.asyncio.client import connect

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import Settings  # noqa: E402
from src.prompt import build_session_update  # noqa: E402


async def main() -> int:
    settings = Settings.from_env()
    if not settings.openai_api_key:
        print("FAIL: OPENAI_API_KEY is not configured")
        return 2
    async with connect(
        settings.openai_realtime_url,
        additional_headers={
            "Authorization": f"Bearer {settings.openai_api_key}",
            "OpenAI-Safety-Identifier": "hpg-voice-config-smoke-test",
        },
        open_timeout=15,
    ) as websocket:
        await websocket.send(
            json.dumps(
                build_session_update(
                    settings.openai_realtime_model,
                    settings.openai_realtime_voice,
                )
            )
        )
        for _ in range(10):
            event = json.loads(await asyncio.wait_for(websocket.recv(), timeout=10))
            if event.get("type") == "session.updated":
                print(
                    "PASS: OpenAI Realtime accepted the session configuration "
                    f"for {settings.openai_realtime_model}"
                )
                return 0
            if event.get("type") == "error":
                error = event.get("error") or {}
                print(
                    "FAIL: OpenAI Realtime rejected the session configuration "
                    f"({error.get('code') or error.get('type') or 'unknown_error'})"
                )
                return 1
    print("FAIL: session.updated was not received")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

