# HPG Voice Gateway — Phase 3 Dispatch Action Contract (Draft)

**Status:** Design draft only. No live voice action is enabled by this document.

## Purpose

Give Hal one controlled action for submitting a caller's service-intake request to HPG Dispatch. This is not appointment booking, calendar availability, technician assignment, or human transfer. Those remain separate capabilities until each has a tested tool and a definitive result.

## Proposed primary action

`submit_appointment_request`

This name follows the HPG Voice Agent Implementation Handoff v1.0. It is an appointment *request* action, not a calendar booking action. The gateway may call it only after the caller has provided the required intake fields and Hal has summarized the request back for confirmation.

## Minimum request fields

- `caller_name`
- `callback_number`
- `service_location_city`
- `service_category`
- `issue_summary`
- `urgency`
- `requested_date` — caller preference; not proof of availability
- `requested_time` — caller preference; not proof of availability
- `requested_timezone`
- `alternate_time` — optional fallback preference
- `onsite_requested` — `yes`, `no`, or `unknown`
- `device_or_system`
- `operating_system` — when relevant to eligibility
- `remote_help_acceptable` — `yes`, `no`, or `unknown`
- `service_plan_claimed` — `yes`, `no`, or `unknown`; initially based on the caller's statement only
- `existing_customer` — `yes`, `no`, or `unknown`
- `call_session_id` — server-generated opaque identifier; never the raw phone number
- `idempotency_key` — server-generated value unique to this submission attempt

Do not collect or transmit passwords, payment details, one-time codes, MFA codes, remote-access codes, full card numbers, Social Security numbers, or other secrets.

## Eligibility and routing flags

The action should return a clear classification before accepting a request:

- `supported` — normal HPG intake
- `out_of_scope` — liquid damage, broken screens, broken keyboards, Android devices, game systems, or Windows 10 and older operating systems
- `emergency` — immediate danger, fire, violence, medical emergency, or active electrical hazard; tell the caller to contact emergency services
- `unsafe_data_loss` — suspected failing drive or active data loss; tell the caller to stop using the device and await professional guidance
- `missing_required_fields` — do not submit yet; Hal asks for the missing normal intake field one at a time

If `service_plan_claimed=yes`, set `priority=true` and route the request to HPG Dispatch for priority handling. Do not claim that account lookup or plan verification occurred until that tool exists.

## Success response

```json
{
  "status": "accepted",
  "request_id": "opaque-dispatch-id",
  "priority": true,
  "next_step": "dispatch_review"
}
```

Only after receiving `status=accepted` may Hal say: “I’ve submitted your request to HPG Dispatch.” Hal must not say an appointment is booked, a technician is assigned, availability was checked, or a human was transferred.

## Failure responses

Use one of these stable results:

- `missing_required_fields` — return the field names only; do not submit
- `out_of_scope` — identify the HPG limitation without promising service
- `duplicate` — return the existing opaque `request_id`; do not create a second request
- `temporarily_unavailable` — tell the caller the request could not be submitted; do not imply it was saved
- `rejected` — return a safe reason code; do not expose internal errors

If the action fails or times out, Hal must say that the request was not submitted and offer to repeat the details or provide the HPG Dispatch contact path. The gateway must never convert a timeout into a success message.

## Companion action contracts (deferred; not live)

The handoff defines these as separate actions. They must not be simulated by the primary action:

- `transfer_to_dispatch` — human-request transfer; requires caller name, callback number, reason, reference when available, and urgency. A successful handoff ends AI handling; a failed handoff offers message capture.
- `create_callback_message` — fallback when transfer is unavailable or the caller requests a callback; requires name, callback number, reason, best callback time, and urgency.
- `flag_service_plan_priority` — internal priority flag when the caller claims an HPG Service Plan. It records the claim only; it does not verify account status.
- `check_onsite_coverage` — authoritative coverage lookup for a ZIP/city/address. If unavailable, Hal must say coverage requires verification.
- `reschedule_request` and `cancel_request` — deferred until an authoritative appointment identifier and result contract exist.

These actions require their own idempotency behavior, definitive result codes, and caller-facing success/failure wording before enablement.

## Handoff field mapping

The implementation should preserve the handoff's call-record vocabulary where present: `caller_name`, `callback_number`, `email`, `customer_type`, `caller_intent`, `device_type`, `operating_system`, `problem_summary`, `service_eligibility`, `remote_candidate`, `onsite_requested`, `service_location`, `appointment_requested`, `requested_date`, `requested_time`, `requested_timezone`, `alternate_time`, `urgency`, `priority`, `transfer_requested`, `transfer_result`, `call_outcome`, `follow_up_required`, `best_callback_time`, and `call_summary`. Any field not required by the selected action remains optional and must not be fabricated.

## HPG Dispatch Command Center mapping (inventory only)

The current HPG Dispatch Command Center is still in safe preview mode: it reports
that sanitized preview records are shown until the Make data webhook is
connected, and its Readiness view marks live GUI webhooks as pending. Its reviewed
job form provides the following compatible destinations for a future voice
request. This is a mapping proposal, not proof that the Make scenario accepts
these fields yet:

| Voice action field | HPG reviewed-job field | Handling |
|---|---|---|
| `caller_name` | Customer name | Required; dispatch-facing |
| `callback_number` | Phone | Required for follow-up; dispatch-facing, not technician-facing |
| `email` | Email | Optional; retain for dispatch/admin only |
| `service_location_city` | City | Required when onsite is requested |
| `service_category` | Service | Map to the closest approved HPG service label |
| `device_or_system` | Device type | Normal intake only |
| `operating_system` | Operating system | Used for eligibility filtering |
| `issue_summary` | Issue summary | Preserve caller meaning; do not include secrets |
| `urgency` | Urgency | Map only to approved normal/today/urgent values |
| `onsite_requested` / remote preference | Appointment type | Map to Onsite, Remote, or Not specified |
| `requested_date` | Appointment date | Preference only; not confirmation |
| `requested_time` | Start time | Preference only; not confirmation |
| `requested_timezone` | No current dedicated field observed | Preserve in the action payload; Make must store it explicitly |
| `service_plan_claimed` / `priority` | No current dedicated field observed | Add a dispatch-only priority/claim field; never claim verification |
| `call_session_id` / `idempotency_key` | No current dedicated field observed | Store as opaque integration metadata for duplicate protection |

The voice action must not invent an assigned technician, end time, customer type,
or booking confirmation. `assigned technician`, `end time`, and any customer-send
checkbox remain staff-reviewed fields unless a later authoritative workflow
returns them.

## Acceptance-test alignment

Before enabling a live action, exercise at minimum HPG-014 (appointment request remains pending), HPG-011 (claimed Service Plan priority), HPG-012 (human/Dispatch request), HPG-013 (failed transfer), HPG-024 (interruption/correction), HPG-026 (duplicate request protection), HPG-027 (prompt injection), and HPG-030 (smoking/sparking emergency). Launch requires the handoff target of at least 90% overall with zero critical failures.

## Idempotency and privacy

- The gateway creates `idempotency_key`; the caller never supplies it.
- A retry with the same key must return the original result rather than create a duplicate.
- Logs may include hashed call references, result codes, and opaque request IDs only.
- Do not log raw phone numbers, names, addresses, issue narratives, transcripts, or action payloads.
- Dispatch and administrators may receive the intake fields; technicians should not receive customer email or phone data unless a later approved workflow explicitly requires it.

## Deferred actions

- Live appointment booking and calendar availability
- Reschedule or cancellation
- Human transfer to the Dispatch Extension
- SMS/email confirmation
- Customer, CRM, or Service Plan lookup
- Technician assignment

Each deferred action requires its own tool contract, definitive success/failure response, idempotency behavior, and caller-facing wording before it is enabled.
