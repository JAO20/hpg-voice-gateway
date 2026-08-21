from __future__ import annotations

import base64
import json
import os
import time
import unittest
from unittest.mock import MagicMock, patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.config import Settings
from src.dispatch_client import _post_json
from src.dispatch_contract import (
    ACTION_NAME,
    build_action_envelope,
    build_idempotency_key,
    caller_message_for_result,
    normalize_action_result,
    validate_appointment_request,
)
from src.prompt import build_initial_greeting, build_session_update
from src.realtime_tools import (
    build_function_output_events,
    prepare_appointment_request,
)
from src.security import stream_token_matches, verify_telnyx_signature
from src.telnyx_api import build_answer_payload


class GatewayTests(unittest.TestCase):
    def test_telnyx_signature_verification(self):
        private_key = Ed25519PrivateKey.generate()
        public_raw = private_key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
        timestamp = str(int(time.time()))
        body = b'{"data":{"id":"evt-1"}}'
        signature = private_key.sign(timestamp.encode() + b"|" + body)
        self.assertTrue(
            verify_telnyx_signature(
                body,
                base64.b64encode(signature).decode(),
                timestamp,
                public_raw.hex(),
            )
        )
        self.assertFalse(
            verify_telnyx_signature(
                body + b"x",
                base64.b64encode(signature).decode(),
                timestamp,
                public_raw.hex(),
            )
        )

    def test_expired_signature_is_rejected(self):
        private_key = Ed25519PrivateKey.generate()
        public_raw = private_key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
        timestamp = "1000"
        body = b"{}"
        signature = private_key.sign(timestamp.encode() + b"|" + body)
        self.assertFalse(
            verify_telnyx_signature(
                body,
                base64.b64encode(signature).decode(),
                timestamp,
                public_raw.hex(),
                now=1401,
            )
        )

    def test_stream_token_accepts_bearer_header(self):
        self.assertTrue(stream_token_matches("Bearer secret", "secret"))
        self.assertFalse(stream_token_matches("Bearer wrong", "secret"))

    def test_stream_token_accepts_telnyx_streaming_auth_header_value(self):
        self.assertTrue(stream_token_matches("secret", "secret"))
        self.assertFalse(stream_token_matches("wrong", "secret"))

    def test_answer_payload_enables_pcmu_bidirectional_stream(self):
        payload = build_answer_payload(
            stream_url="wss://voice.example/telnyx/media",
            stream_auth_token="secret",
            command_id="evt-1",
        )
        self.assertEqual(payload["stream_track"], "inbound_track")
        self.assertEqual(payload["stream_codec"], "PCMU")
        self.assertEqual(payload["stream_bidirectional_mode"], "rtp")
        self.assertEqual(payload["stream_bidirectional_codec"], "PCMU")
        self.assertEqual(payload["stream_bidirectional_sampling_rate"], 8000)

    def test_openai_session_uses_pcmu_and_selected_voice(self):
        event = build_session_update("gpt-realtime-2.1", "marin")
        session = event["session"]
        self.assertEqual(session["audio"]["input"]["format"]["type"], "audio/pcmu")
        self.assertEqual(session["audio"]["output"]["format"]["type"], "audio/pcmu")
        self.assertEqual(session["audio"]["output"]["voice"], "marin")
        self.assertTrue(session["audio"]["input"]["turn_detection"]["interrupt_response"])

    def test_receptionist_prompt_keeps_dispatch_boundary(self):
        event = build_session_update("gpt-realtime-2.1", "marin")
        instructions = event["session"]["instructions"]
        self.assertIn("Half Price Geeks' AI virtual receptionist", instructions)
        self.assertIn("Appointment-request tools are not connected", instructions)
        self.assertIn("Never claim an appointment is booked", instructions)
        self.assertIn("Do not ask for passwords", instructions)
        self.assertNotIn("tools", event["session"])

    def test_receptionist_prompt_contains_verified_handoff_rules(self):
        instructions = build_session_update(
            "gpt-realtime-2.1", "marin", dispatch_enabled=True
        )["session"]["instructions"]
        required_rules = (
            "remote service nationwide",
            "Onsite service is available only where technician coverage exists",
            "Windows 10 or older",
            "liquid damage",
            "Service Plan",
            "request-only",
            "existing request status",
            "Please don't give me your password or security code",
            "contact 911",
            "Confirm you reached the intended person",
            "Honor \"do not call\"",
        )
        for rule in required_rules:
            with self.subTest(rule=rule):
                self.assertIn(rule, instructions)

    def test_dispatch_tool_is_only_exposed_when_fully_enabled(self):
        event = build_session_update(
            "gpt-realtime-2.1", "marin", dispatch_enabled=True
        )
        session = event["session"]
        self.assertEqual(session["tool_choice"], "auto")
        self.assertEqual(session["tools"][0]["name"], ACTION_NAME)
        self.assertNotIn(
            "call_session_id",
            session["tools"][0]["parameters"]["properties"],
        )
        self.assertIn("request was submitted for team confirmation", session["instructions"])

    def test_initial_greeting_is_hpg_receptionist_not_transport_test(self):
        event = build_initial_greeting()
        instructions = event["response"]["instructions"]
        self.assertIn("Thanks for calling Half Price Geeks", instructions)
        self.assertNotIn("voice-system test", instructions)

    def test_settings_builds_wss_media_url(self):
        env = {
            "PUBLIC_BASE_URL": "https://voice.example/",
            "OPENAI_API_KEY": "present",
            "TELNYX_API_KEY": "present",
            "TELNYX_PUBLIC_KEY": "present",
            "TELNYX_STREAM_AUTH_TOKEN": "present",
        }
        with patch.dict(os.environ, env, clear=True):
            settings = Settings.from_env(load_local=False)
        self.assertEqual(settings.media_stream_url, "wss://voice.example/telnyx/media")
        self.assertEqual(settings.missing_runtime_values(), [])
        self.assertFalse(settings.dispatch_enabled)

    def test_dispatch_requires_both_endpoint_and_auth_token(self):
        base = {
            "PUBLIC_BASE_URL": "https://voice.example/",
            "OPENAI_API_KEY": "present",
            "TELNYX_API_KEY": "present",
            "TELNYX_PUBLIC_KEY": "present",
            "TELNYX_STREAM_AUTH_TOKEN": "present",
        }
        with patch.dict(
            os.environ,
            {**base, "MAKE_DISPATCH_WEBHOOK_URL": "https://hook.example/voice"},
            clear=True,
        ):
            self.assertFalse(Settings.from_env(load_local=False).dispatch_enabled)
        with patch.dict(
            os.environ,
            {
                **base,
                "MAKE_DISPATCH_WEBHOOK_URL": "https://hook.example/voice",
                "MAKE_DISPATCH_AUTH_TOKEN": "present",
            },
            clear=True,
        ):
            self.assertTrue(Settings.from_env(load_local=False).dispatch_enabled)

    def test_dispatch_contract_requires_normal_intake_fields(self):
        result = validate_appointment_request(
            {
                "caller_name": "Oliver",
                "callback_number": "555-0100",
                "service_category": "computer repair",
                "issue_summary": "Laptop will not start",
                "requested_date": "2026-08-25",
                "requested_time": "10:00",
                "requested_timezone": "America/Chicago",
                "remote_help_acceptable": "yes",
                "service_plan_claimed": "yes",
                "call_session_id": "opaque-call-1",
            }
        )
        self.assertTrue(result["valid"])
        self.assertEqual(result["action"], ACTION_NAME)
        self.assertTrue(result["priority"])
        self.assertFalse(result["service_plan_verified"])

    def test_dispatch_contract_requires_location_for_onsite_request(self):
        result = validate_appointment_request(
            {
                "caller_name": "Oliver",
                "callback_number": "555-0100",
                "service_category": "computer repair",
                "issue_summary": "Laptop will not start",
                "requested_date": "2026-08-25",
                "requested_time": "10:00",
                "requested_timezone": "America/Chicago",
                "remote_help_acceptable": "no",
                "onsite_requested": "yes",
                "call_session_id": "opaque-call-2",
            }
        )
        self.assertEqual(result["status"], "missing_required_fields")
        self.assertIn("service_location_city", result["missing_fields"])

    def test_dispatch_contract_rejects_secret_fields(self):
        result = validate_appointment_request({"caller_name": "Oliver", "password": "never"})
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["reason_code"], "secret_field")

    def test_idempotency_key_is_stable_and_opaque(self):
        first = build_idempotency_key("opaque-call-1")
        second = build_idempotency_key("opaque-call-1")
        self.assertEqual(first, second)
        self.assertEqual(len(first), 64)
        self.assertNotIn("opaque-call-1", first)

    def test_action_result_only_accepts_success_with_request_id(self):
        self.assertTrue(normalize_action_result({"status": "accepted", "request_id": "req-1"})["accepted"])
        failed = normalize_action_result({"status": "accepted"})
        self.assertFalse(failed["accepted"])
        self.assertEqual(failed["status"], "rejected")
        self.assertEqual(failed["reason_code"], "missing_request_id")

    def test_action_envelope_contains_only_safe_fields_and_server_idempotency(self):
        envelope = build_action_envelope(
            {
                "caller_name": "Oliver",
                "callback_number": "555-0100",
                "service_category": "computer repair",
                "issue_summary": "Laptop will not start",
                "device_or_system": "laptop",
                "requested_date": "2026-08-25",
                "requested_time": "10:00",
                "requested_timezone": "America/Chicago",
                "remote_help_acceptable": "yes",
                "service_plan_claimed": "yes",
                "call_session_id": "opaque-call-3",
                "password": "must-not-pass",
            }
        )
        self.assertEqual(envelope["status"], "rejected")

        clean = build_action_envelope(
            {
                "caller_name": "Oliver",
                "callback_number": "555-0100",
                "service_category": "computer repair",
                "issue_summary": "Laptop will not start",
                "device_or_system": "laptop",
                "requested_date": "2026-08-25",
                "requested_time": "10:00",
                "requested_timezone": "America/Chicago",
                "remote_help_acceptable": "yes",
                "service_plan_claimed": "yes",
                "call_session_id": "opaque-call-3",
            }
        )
        self.assertTrue(clean["valid"])
        self.assertEqual(clean["data"]["action"], ACTION_NAME)
        self.assertTrue(clean["data"]["priority"])
        self.assertNotIn("password", clean["data"])

    def test_empty_or_unknown_action_results_cannot_sound_successful(self):
        self.assertEqual(normalize_action_result(None)["status"], "temporarily_unavailable")
        self.assertIn("couldn't submit", caller_message_for_result({"status": "timeout"}))

    def test_dispatch_client_requires_https_and_request_id(self):
        invalid = _post_json("http://hook.example", "token", {"safe": True}, 1)
        self.assertEqual(invalid["reason_code"], "invalid_endpoint")

        response = MagicMock()
        response.read.return_value = json.dumps({"status": "accepted"}).encode()
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        with patch("src.dispatch_client.urlopen", return_value=response) as open_mock:
            result = _post_json(
                "https://hook.example/voice", "token", {"safe": True}, 1
            )
        self.assertFalse(result["accepted"])
        self.assertEqual(result["reason_code"], "missing_request_id")
        sent_request = open_mock.call_args.args[0]
        self.assertEqual(sent_request.get_header("X-make-apikey"), "token")
        self.assertIsNone(sent_request.get_header("Authorization"))


class RealtimeToolTests(unittest.TestCase):
    def test_realtime_tool_uses_server_call_ref_and_returns_safe_message(self):
        arguments = {
            "caller_name": "Synthetic Caller",
            "callback_number": "555-0100",
            "service_category": "computer repair",
            "issue_summary": "Synthetic laptop issue",
            "requested_date": "2026-08-25",
            "requested_time": "10:00",
            "requested_timezone": "America/Chicago",
            "remote_help_acceptable": "yes",
            "call_session_id": "model-must-not-control-this",
        }
        prepared = prepare_appointment_request(
            json.dumps(arguments), "server-owned-call-ref"
        )
        self.assertTrue(prepared["ready"])
        sent_envelope = prepared["envelope"]
        self.assertEqual(sent_envelope["call_session_id"], "server-owned-call-ref")
        self.assertNotEqual(sent_envelope["call_session_id"], arguments["call_session_id"])
        output_event, response_event = build_function_output_events(
            "function-call-1",
            {"status": "accepted", "request_id": "req-1", "accepted": True},
        )
        output = json.loads(output_event["item"]["output"])
        self.assertTrue(output["accepted"])
        self.assertIn("submitted your appointment request", output["caller_message"])
        self.assertIn("Do not add any claim", response_event["response"]["instructions"])

    def test_realtime_tool_rejects_malformed_arguments_without_network(self):
        prepared = prepare_appointment_request("not-json", "server-call-ref")
        self.assertFalse(prepared["ready"])
        output_event, _ = build_function_output_events(
            "function-call-2", prepared["result"]
        )
        output = json.loads(output_event["item"]["output"])
        self.assertFalse(output["accepted"])
        self.assertIn("couldn't submit", output["caller_message"])


if __name__ == "__main__":
    unittest.main()
