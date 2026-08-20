"""Pure validation and result handling for the Phase 3 appointment-request action.

This module is intentionally not imported by the live gateway yet.  It provides a
small, deterministic boundary for the future Make/HPG Dispatch connector so an
ambiguous or failed external result can never be spoken as a successful request.
"""

from __future__ import annotations

import hashlib
from typing import Any, Mapping


ACTION_NAME = "submit_appointment_request"

ACCEPTED_STATUSES = {
    "accepted",
    "missing_required_fields",
    "out_of_scope",
    "duplicate",
    "temporarily_unavailable",
    "rejected",
}

FORBIDDEN_FIELDS = {
    "password",
    "payment_details",
    "card_number",
    "full_card_number",
    "one_time_code",
    "otp",
    "mfa_code",
    "remote_access_code",
    "social_security_number",
    "ssn",
}

BASE_REQUIRED_FIELDS = (
    "caller_name",
    "callback_number",
    "service_category",
    "issue_summary",
    "requested_date",
    "requested_time",
    "requested_timezone",
    "remote_help_acceptable",
    "call_session_id",
)


def build_idempotency_key(
    call_session_id: str,
    action_purpose: str = ACTION_NAME,
    relevant_reference: str = "",
) -> str:
    """Return a stable opaque key without incorporating caller PII."""

    if not call_session_id.strip():
        raise ValueError("call_session_id is required")
    material = "|".join(
        (call_session_id.strip(), action_purpose.strip(), relevant_reference.strip())
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def validate_appointment_request(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a proposed request and derive safe routing fields.

    The caller's Service Plan statement becomes a priority *claim* only.  Plan
    verification is deliberately not represented as successful here.
    """

    supplied = {str(key) for key in payload}
    forbidden = sorted(supplied.intersection(FORBIDDEN_FIELDS))
    if forbidden:
        return {"valid": False, "status": "rejected", "reason_code": "secret_field"}

    missing = sorted(
        field
        for field in BASE_REQUIRED_FIELDS
        if not str(payload.get(field, "")).strip()
    )
    onsite_requested = str(payload.get("onsite_requested", "unknown")).lower()
    if onsite_requested == "yes" and not str(
        payload.get("service_location_city", "")
    ).strip():
        missing.append("service_location_city")
    if missing:
        return {
            "valid": False,
            "status": "missing_required_fields",
            "missing_fields": sorted(set(missing)),
        }

    service_plan_claimed = str(payload.get("service_plan_claimed", "unknown")).lower()
    return {
        "valid": True,
        "status": "ready",
        "action": ACTION_NAME,
        "priority": service_plan_claimed == "yes",
        "service_plan_claimed": service_plan_claimed,
        "service_plan_verified": False,
        "onsite_requested": onsite_requested,
    }


def normalize_action_result(result: Mapping[str, Any] | None) -> dict[str, Any]:
    """Normalize an external result into a small, safe caller-facing contract."""

    if not result:
        return {
            "status": "temporarily_unavailable",
            "reason_code": "empty_result",
            "accepted": False,
        }

    status = str(result.get("status", "")).lower()
    if status not in ACCEPTED_STATUSES:
        status = "rejected"
        reason_code = "unknown_result"
    else:
        reason_code = str(result.get("reason_code", "")) or None

    request_id = str(result.get("request_id", "")).strip() or None
    accepted = status == "accepted" and request_id is not None
    if status == "accepted" and not accepted:
        status = "rejected"
        reason_code = "missing_request_id"

    return {
        "status": status,
        "request_id": request_id,
        "reason_code": reason_code,
        "accepted": accepted,
    }


def build_action_envelope(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Build the provider-neutral payload for the future Dispatch connector."""

    validation = validate_appointment_request(payload)
    if not validation["valid"]:
        return validation

    call_session_id = str(payload["call_session_id"]).strip()
    idempotency_key = build_idempotency_key(call_session_id)
    safe_fields = (
        "caller_name",
        "callback_number",
        "email",
        "customer_type",
        "service_category",
        "issue_summary",
        "device_or_system",
        "operating_system",
        "remote_help_acceptable",
        "onsite_requested",
        "service_location_city",
        "requested_date",
        "requested_time",
        "requested_timezone",
        "alternate_time",
        "urgency",
        "existing_customer",
        "service_plan_claimed",
    )
    data = {
        field: payload[field]
        for field in safe_fields
        if field in payload and str(payload[field]).strip()
    }
    data.update(
        {
            "action": ACTION_NAME,
            "priority": validation["priority"],
            "service_plan_verified": False,
            "call_session_id": call_session_id,
            "idempotency_key": idempotency_key,
        }
    )
    return {"valid": True, "action": ACTION_NAME, "data": data}


def caller_message_for_result(result: Mapping[str, Any] | None) -> str:
    """Return conservative wording; only an accepted result says submitted."""

    normalized = normalize_action_result(result)
    status = normalized["status"]
    if status == "accepted":
        return "I've submitted your appointment request. The team will confirm the final appointment details."
    if status == "duplicate":
        return "I found an existing request for this call, so I did not create a duplicate."
    if status == "missing_required_fields":
        return "I still need one or more normal appointment details before I can submit the request."
    if status == "out_of_scope":
        return "That request is outside the services Half Price Geeks currently provides."
    if status == "temporarily_unavailable":
        return "I couldn't submit the request right now. I can repeat the details or take a message."
    return "I couldn't submit the request. I can repeat the details or take a message."
