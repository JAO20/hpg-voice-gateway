"""Pure Realtime function-call preparation and response helpers."""

from __future__ import annotations

import json
from typing import Any, Mapping

from .dispatch_contract import build_action_envelope, caller_message_for_result


def prepare_appointment_request(arguments_json: str, call_ref: str) -> dict[str, Any]:
    """Validate model arguments while forcing the server-owned call identity."""

    try:
        arguments = json.loads(arguments_json or "{}")
    except json.JSONDecodeError:
        arguments = None
    if not isinstance(arguments, dict):
        return {
            "ready": False,
            "result": {
                "status": "rejected",
                "reason_code": "invalid_arguments",
                "accepted": False,
            },
        }

    arguments["call_session_id"] = call_ref
    envelope = build_action_envelope(arguments)
    if not envelope.get("valid"):
        return {
            "ready": False,
            "result": {
                "status": envelope.get("status", "rejected"),
                "reason_code": envelope.get("reason_code"),
                "missing_fields": envelope.get("missing_fields", []),
                "accepted": False,
            },
        }
    return {"ready": True, "envelope": envelope["data"]}


def build_function_output_events(
    call_id: str, result: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return the documented Realtime output item and constrained response turn."""

    safe_result = dict(result)
    safe_result["caller_message"] = caller_message_for_result(safe_result)
    output_event = {
        "type": "conversation.item.create",
        "item": {
            "type": "function_call_output",
            "call_id": call_id,
            "output": json.dumps(safe_result, separators=(",", ":")),
        },
    }
    response_event = {
        "type": "response.create",
        "response": {
            "output_modalities": ["audio"],
            "instructions": (
                "Speak the caller_message from the tool output naturally and briefly. "
                "Do not add any claim that the appointment is booked, scheduled, "
                "confirmed, assigned, or all set."
            ),
        },
    }
    return output_event, response_event
