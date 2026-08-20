# HPG Voice Gateway

Phase 1 gateway for Half Price Geeks. It accepts signed Telnyx Voice API
webhooks, answers inbound test calls with an authenticated bidirectional PCMU
media stream, and relays that audio to an OpenAI Realtime voice session. An
off-by-default Phase 3 boundary can expose one caller-approved appointment-
request action after its private Make endpoint is configured and validated.

This repository contains no passwords, API keys, tokens, customer records, or
other secret values.

## Verified architecture

1. Telnyx sends a signed `call.initiated` webhook to
   `POST /telnyx/webhooks`.
2. The gateway verifies the Ed25519 signature and answers the incoming call.
3. Telnyx opens an authenticated WebSocket at `WSS /telnyx/media` using PCMU,
   8 kHz, bidirectional RTP media.
4. The gateway connects server-to-server to OpenAI Realtime, also using PCMU.
5. Incoming Telnyx media becomes `input_audio_buffer.append` events.
6. OpenAI `response.output_audio.delta` audio returns to the Telnyx stream.
7. Telnyx marks plus OpenAI speech-start events support queue clearing and
   conversation truncation when a caller interrupts.

## Current limits

- The Hal prompt is a friendly, down-to-earth receptionist prompt with strict
  request-only language.
- The appointment-request tool stays absent from Realtime unless both private
  Make variables are present. It can submit a request, never book or confirm an
  appointment.
- Calendar availability, customer lookup, SMS, scheduling, and transfer tools
  are not connected.
- No call recording is enabled.
- The in-memory webhook duplicate cache is backed by Telnyx command IDs. A
  durable idempotency store should be added before broader production use.

## Configuration

Copy only the variable **names** from `.env.example` into the deployment
environment. Store values in the hosting provider's secret-variable system.

Required variable names:

- `PUBLIC_BASE_URL`
- `OPENAI_API_KEY`
- `OPENAI_REALTIME_MODEL` (default: `gpt-realtime-2.1`)
- `OPENAI_REALTIME_VOICE` (default: `marin`)
- `TELNYX_API_KEY`
- `TELNYX_PUBLIC_KEY`
- `TELNYX_STREAM_AUTH_TOKEN`
- `MAKE_DISPATCH_WEBHOOK_URL` (optional; must be paired with the auth token)
- `MAKE_DISPATCH_AUTH_TOKEN` (optional; must be paired with the webhook URL)
- `MAKE_DISPATCH_TIMEOUT_SECONDS` (default: `8`)
- `PORT` (provided by Railway)

The gateway sends `MAKE_DISPATCH_AUTH_TOKEN` only in Make's protected
`x-make-apikey` request header. Never place the value in source control, logs,
prompts, screenshots, or project documentation.

## Local validation

```bash
python -m compileall -q src tests scripts
python -m unittest discover -s tests -v
python scripts/smoke_openai_realtime.py
```

The final smoke test makes a short authenticated Realtime connection and checks
that OpenAI accepts the session configuration. It does not make a telephone
call.

## Railway deployment

The repository includes `railway.json` and a `Procfile`. Connect this folder to
the Railway service, add required variables, generate a public domain, and use:

- Health check: `GET /healthz`
- Telnyx webhook URL: `https://<domain>/telnyx/webhooks`
- Telnyx media URL: derived automatically as `wss://<domain>/telnyx/media`

Do not expose secret values in deployment notes, screenshots, logs, or the
Master State.

## Primary documentation

- OpenAI Realtime WebSocket:
  https://developers.openai.com/api/docs/guides/realtime-websocket
- OpenAI Realtime conversations:
  https://developers.openai.com/api/docs/guides/realtime-conversations
- Telnyx media streaming:
  https://developers.telnyx.com/docs/voice/programmable-voice/media-streaming
- Telnyx webhook handling:
  https://developers.telnyx.com/docs/development/api-fundamentals/webhooks/receiving-webhooks
