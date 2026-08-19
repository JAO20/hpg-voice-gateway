from __future__ import annotations

import base64
import os
import time
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.config import Settings
from src.prompt import build_session_update
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


if __name__ == "__main__":
    unittest.main()

