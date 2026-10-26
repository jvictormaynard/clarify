# Connect an iPhone to a computer

This feature adds a paired computer as a separate processing destination. The
existing Clarify account destination keeps its authentication, quota and history
contracts. Computer processing uses the computer's own provider configuration.

The desktop owner is an opt-in host service. The containing iOS app owns scanning,
pairing, credentials and transport. The keyboard receives only the existing
nonsecret recording state and completed text. It receives no device credential,
provider key or account session.

## Pairing contract, version 1

The desktop displays a QR code with this URL:

```text
clarify://computer?data=<base64url UTF-8 JSON, without padding>
```

The JSON fields are:

```json
{
  "schema_version": 1,
  "computer_id": "<UUID>",
  "computer_name": "<display name>",
  "routes": [
    {
      "url": "https://<computer LAN address>:47653",
      "certificate_sha256": "<SHA-256 of the DER TLS certificate>"
    }
  ],
  "pairing_token": "<32 random bytes, base64url without padding>",
  "expires_at": "<UTC ISO-8601 timestamp>"
}
```

The bootstrap token expires after five minutes and can be used once. Creating a
new QR invalidates the previous token. The app discards this token after pairing.
Only the explicitly supplied routes can receive a pairing or device credential.
Redirects are refused. A LAN route requires the exact scanned certificate hash.
A route with a null hash requires normal system TLS trust.

Pairing returns a separate revocable credential for each device. The app keeps it
in its private Keychain. The computer persists token hashes and bounded operation
state in its own SQLite store. Its private TLS identity uses the desktop secret
store. A Settings snapshot must not expose permanent device credentials.

## Processing API

| Request | Body or result |
| --- | --- |
| `POST /v1/computer/pair` | `{pairing_token, device_name}`; returns `{schema_version, computer_id, computer_name, device_id, session_token}` |
| `GET /v1/computer/status` | Returns `{schema_version, computer_id, computer_name, ready}` |
| `POST /v1/computer/dictations` | `{operation_id, language, audio_wav}` |
| `POST /v1/computer/text` | `{operation_id, action, text, language}`; action is `rewrite` or `translate` |
| `DELETE /v1/computer/operations/<UUID>` | Cancels the caller's operation |
| `DELETE /v1/computer/session` | Revokes the caller's credential |

All routes except pairing require `Authorization: Bearer <session_token>`.
Dictation and text return
`{operation_id, transcript, text, rewritten, successful}`. Errors return a bounded
`{error}` code with a suitable HTTP status, without provider exception bodies.

Audio is base64-encoded PCM16 mono WAV at 16 kHz, with a maximum duration of
300 seconds. The complete JSON request has a 16 MiB limit. The mobile converts
its recorded AAC clip before upload and removes its temporary WAV on every
terminal path. The computer owns its temporary input until processing ends.
Text input and each result text field have a 32 KiB UTF-8 limit, matching the
native history contract. Oversized results fail without truncation.

Operation IDs are UUIDs scoped to the paired device. An identical retry reuses a
bounded stored result. Different content with the same ID is rejected. An
uncertain or expired operation must not automatically start expensive work again.
Cancellation and device revocation prevent a late result from being published.

The computer selects providers, models, prompts and its dictionary. The mobile
cannot supply provider credentials, arbitrary endpoints, file paths or tools.
Computer-scoped history must not enter account synchronization. Switching
destinations invalidates old operations and recording ownership. An unavailable
computer cannot silently select hosted processing.

## Delivery evidence

This protocol describes the implementation boundary. It does not establish
Windows package acceptance, iPhone network acceptance, internet tunnel
availability or TestFlight availability. Those gates require evidence from the
exact delivered candidate.
