from __future__ import annotations

import asyncio
import json
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


class TelnyxAPIError(RuntimeError):
    pass


def build_answer_payload(
    *,
    stream_url: str,
    stream_auth_token: str,
    command_id: str,
) -> dict:
    return {
        "command_id": command_id,
        "stream_url": stream_url,
        "stream_track": "inbound_track",
        "stream_codec": "PCMU",
        "stream_bidirectional_mode": "rtp",
        "stream_bidirectional_codec": "PCMU",
        "stream_bidirectional_sampling_rate": 8000,
        "stream_bidirectional_target_legs": "self",
        "stream_auth_token": stream_auth_token,
    }


def _post_json(url: str, api_key: str, payload: dict) -> dict:
    body = json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=10) as response:
            response_body = response.read()
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise TelnyxAPIError(f"Telnyx HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise TelnyxAPIError(f"Telnyx connection error: {exc.reason}") from exc

    if not response_body:
        return {}
    return json.loads(response_body.decode("utf-8"))


async def answer_call(
    call_control_id: str,
    *,
    api_key: str,
    stream_url: str,
    stream_auth_token: str,
    command_id: str,
) -> dict:
    escaped_id = quote(call_control_id, safe="")
    url = f"https://api.telnyx.com/v2/calls/{escaped_id}/actions/answer"
    payload = build_answer_payload(
        stream_url=stream_url,
        stream_auth_token=stream_auth_token,
        command_id=command_id,
    )
    return await asyncio.to_thread(_post_json, url, api_key, payload)

