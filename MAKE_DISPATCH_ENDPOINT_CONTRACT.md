# HPG Voice → Make Dispatch Endpoint Contract

**Status:** Implementation specification only. No webhook URL, secret, live
scenario, or caller-facing action is enabled by this document.

## Current Make compatibility assessment (2026-08-20)

The authenticated Make inventory found an active `HPG – Public Dispatch Intake`
scenario whose custom webhook is `HPG Elementor Service Request`. Its detected
inputs are Elementor/form labels (28 values), and its primary write target is
the `HPG Dispatch Dashboard` → `Dispatch` sheet. The route contains two Google
Sheets `Add a Row` branches and an HTTP module. This is useful operational
evidence, but it is not a verified voice-action endpoint.

The voice contract therefore requires one of these two controlled designs before
any live connection:

1. **Preferred:** a separate protected custom webhook for the canonical voice
   JSON below, with an explicit response module returning the stable statuses in
   this document; or
2. **Guarded adapter:** a separate first module that validates and maps the voice
   JSON into the existing dispatch record shape, while preserving the existing
   Elementor webhook and its routes unchanged.

Do not send voice payloads directly to the Elementor webhook. Its form field
   names, derived identifiers, and downstream HTTP behavior have not been
   verified as safe or authoritative for a voice action.

The currently observed dispatch-sheet mapping is useful for adapter review only:
`caller_name` → Name, `callback_number` → Phone, `email` → Email,
`service_location_city` → City, `service_category` → Service Requested,
`device_or_system` → Device/System, `operating_system` → Operating System,
`issue_summary` → Problem Details, `urgency` → Urgency,
`requested_date`/`requested_time` → Preferred Day/Preferred Time, and
`idempotency_key` → Idempotency Key. Phone and email remain Dispatch/admin-only.
The existing sheet has additional operational, calendar, and opaque-ID columns;
those must be assigned by the adapter or Make scenario, never invented by Hal.

## Purpose

Provide one protected Make intake endpoint for Hal's future
`submit_appointment_request` action. The endpoint creates or forwards a pending
HPG Dispatch request; it does not book a calendar appointment, assign a
technician, send customer communications, or expose technician-only data.

## Inbound request

The gateway sends JSON with the canonical action name and only normal intake
fields. The following is a synthetic shape; it contains no real customer data:

```json
{
  "action": "submit_appointment_request",
  "idempotency_key": "server-generated-opaque-hash",
  "call_session_id": "server-generated-opaque-session",
  "caller_name": "Test Caller",
  "callback_number": "synthetic-test-number",
  "email": "optional@example.invalid",
  "customer_type": "residential",
  "service_category": "computer repair",
  "issue_summary": "Synthetic test issue",
  "device_or_system": "Windows laptop",
  "operating_system": "Windows 11",
  "remote_help_acceptable": "yes",
  "onsite_requested": "no",
  "service_location_city": "Waco",
  "requested_date": "2026-08-25",
  "requested_time": "10:00",
  "requested_timezone": "America/Chicago",
  "alternate_time": "",
  "urgency": "normal",
  "existing_customer": "unknown",
  "service_plan_claimed": "yes",
  "priority": true,
  "service_plan_verified": false
}
```

The gateway must generate `idempotency_key` and `call_session_id`; callers must
never supply either value. `priority=true` is derived only from the caller's
Service Plan claim. It is not proof of account verification.

## Make processing requirements

1. Authenticate the request with Make's protected `x-make-apikey` header. Never
   put the credential value in the prompt, caller audio, logs, screenshots, or
   documentation.
2. Validate the action name and required fields before any write.
3. Reject passwords, payment data, card numbers, OTP/MFA codes, remote-access
   codes, SSNs, and other secrets.
4. Check `idempotency_key` before creating a second request. A retry must return
   the original result.
5. Create or forward a **pending/requested** HPG Dispatch record only. Do not
   mark it booked, scheduled, confirmed, assigned, or completed.
6. Preserve caller phone/email for Dispatch and administrators only. Do not put
   them in technician-facing notifications or views unless a later approved
   workflow explicitly requires it.
7. Return one stable JSON response and an appropriate HTTP status. Do not return
   internal stack traces, private URLs, credentials, or raw provider errors.

## Response contract

### Accepted

```json
{
  "status": "accepted",
  "request_id": "opaque-dispatch-id",
  "priority": true,
  "next_step": "dispatch_review"
}
```

Only this response, with a non-empty opaque `request_id`, permits Hal to say:

> I've submitted your appointment request. The team will confirm the final appointment details.

This still does **not** permit Hal to say booked, scheduled, confirmed, assigned,
or “you're all set.”

### Non-success statuses

Use one of these stable results:

| Status | Meaning | Hal's behavior |
|---|---|---|
| `missing_required_fields` | Normal intake is incomplete | Ask only for the missing normal field; do not submit |
| `out_of_scope` | HPG does not support the request | Explain the limitation; do not promise service |
| `duplicate` | Same idempotency key already exists | Do not create another request; use the existing opaque ID internally |
| `temporarily_unavailable` | Timeout, unavailable scenario, or transient failure | Say it was not submitted; offer repeat or message capture |
| `rejected` | Validation or safe-policy rejection | Say it was not submitted; do not expose internal details |

No timeout, empty response, malformed response, or unknown status may be
converted into `accepted`.

## Test plan before activation

Use synthetic data only until the endpoint passes:

- accepted request returns an opaque request ID;
- duplicate submission returns the original ID and creates no second record;
- missing field is rejected without a write;
- onsite request without city is rejected without a write;
- claimed Service Plan sets priority but remains unverified;
- unsupported service is rejected without a write;
- timeout/empty/unknown response is treated as failure;
- secret-bearing payload is rejected;
- technician-facing output omits phone and email;
- no customer message, SMS, calendar booking, transfer, or technician assignment occurs.

Live enablement requires the endpoint URL, authentication method, Make scenario
mapping, test evidence, and action-time approval before any real caller data is
transmitted.
