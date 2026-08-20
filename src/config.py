from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def load_env_file(path: Path) -> None:
    """Load a small dotenv file without logging or overwriting process values."""
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip().strip("\"").strip("'")
        if name and name not in os.environ:
            os.environ[name] = value


def _clean_url(value: str) -> str:
    return value.strip().rstrip("/")


@dataclass(frozen=True)
class Settings:
    environment: str
    port: int
    public_base_url: str
    openai_api_key: str
    openai_realtime_model: str
    openai_realtime_voice: str
    telnyx_api_key: str
    telnyx_public_key: str
    telnyx_stream_auth_token: str
    make_dispatch_webhook_url: str
    make_dispatch_auth_token: str
    make_dispatch_timeout_seconds: float

    @property
    def media_stream_url(self) -> str:
        if self.public_base_url.startswith("https://"):
            base = "wss://" + self.public_base_url.removeprefix("https://")
        elif self.public_base_url.startswith("http://"):
            base = "ws://" + self.public_base_url.removeprefix("http://")
        else:
            base = self.public_base_url
        return f"{base}/telnyx/media"

    @property
    def openai_realtime_url(self) -> str:
        return (
            "wss://api.openai.com/v1/realtime?model="
            f"{self.openai_realtime_model}"
        )

    @property
    def dispatch_enabled(self) -> bool:
        return bool(
            self.make_dispatch_webhook_url and self.make_dispatch_auth_token
        )

    def missing_runtime_values(self) -> list[str]:
        required = {
            "PUBLIC_BASE_URL": self.public_base_url,
            "OPENAI_API_KEY": self.openai_api_key,
            "TELNYX_API_KEY": self.telnyx_api_key,
            "TELNYX_PUBLIC_KEY": self.telnyx_public_key,
            "TELNYX_STREAM_AUTH_TOKEN": self.telnyx_stream_auth_token,
        }
        return [name for name, value in required.items() if not value]

    @classmethod
    def from_env(cls, *, load_local: bool = True) -> "Settings":
        if load_local:
            load_env_file(Path(".env.local"))
            load_env_file(Path(".env"))
        return cls(
            environment=os.getenv("ENVIRONMENT", "development").strip().lower(),
            port=int(os.getenv("PORT", "8080")),
            public_base_url=_clean_url(os.getenv("PUBLIC_BASE_URL", "")),
            openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
            openai_realtime_model=os.getenv(
                "OPENAI_REALTIME_MODEL", "gpt-realtime-2.1"
            ).strip(),
            openai_realtime_voice=os.getenv(
                "OPENAI_REALTIME_VOICE", "marin"
            ).strip(),
            telnyx_api_key=os.getenv("TELNYX_API_KEY", "").strip(),
            telnyx_public_key=os.getenv("TELNYX_PUBLIC_KEY", "").strip(),
            telnyx_stream_auth_token=os.getenv(
                "TELNYX_STREAM_AUTH_TOKEN", ""
            ).strip(),
            make_dispatch_webhook_url=_clean_url(
                os.getenv("MAKE_DISPATCH_WEBHOOK_URL", "")
            ),
            make_dispatch_auth_token=os.getenv(
                "MAKE_DISPATCH_AUTH_TOKEN", ""
            ).strip(),
            make_dispatch_timeout_seconds=float(
                os.getenv("MAKE_DISPATCH_TIMEOUT_SECONDS", "8")
            ),
        )
