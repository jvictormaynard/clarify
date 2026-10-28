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

An optional shared byte relay adds a remote route. Its public build configuration
is `shared/computer_connect.json`: `relay_host` is a lowercase public DNS name or
null, and `relay_port` is the public TCP port. Desktop and iOS builds use this
same file. A null host preserves direct LAN access and does not contact a relay.
The candidate has no public relay domain or deployment configured.

The remote route is `https://<namespace>.<relay-host>[:port]`. The namespace is
lowercase, unpadded Base32 of the 32-byte SHA-256 digest of the desktop leaf DER
certificate. The route carries that same exact certificate pin. It identifies
the computer independently of its current LAN addresses. The relay owns neither
the desktop TLS private key nor a processing credential. The phone's inner TLS
session ends at the desktop. The relay forwards encrypted bytes over the
desktop's outgoing, CA-validated TLS connection.

The native client probes trusted routes serially before selecting one. A private
LAN probe has a 1.5-second deadline; a public DNS probe has a five-second deadline.
Pairing probes status without a token, then submits one pairing POST. An uncertain
pairing or processing reply cannot trigger another POST through a different route.
Cancellation and destination changes invalidate stale discovery results.

iOS applies a scoped ATS exception only to the configured relay domain and its
subdomains. Native requests still require HTTPS, TLS 1.2 or later and the exact
desktop certificate. The parser rejects the relay apex, nested namespaces,
incorrect pins and CA-only routes in that scope. See
[native trust and acceptance](../mobile/README.md#optional-relay-build-configuration-and-trust)
and [relay operation and limits](../connect/README.md).

Pairing returns a separate revocable credential for each device. The app keeps it
in its private Keychain. The computer persists token hashes and bounded operation
state in its own SQLite store. Its private TLS identity uses the desktop secret
store. A Settings snapshot must not expose permanent device credentials.

## Processing API

| Request | Body or result |
| --- | --- |
| `POST /v1/computer/pair` | `{pairing_token, device_name}`; returns `{schema_version, computer_id, computer_name, device_id, session_token}` |
| `GET /v1/computer/status` | Returns `{schema_version, computer_id, computer_name, ready, action_readiness}` |
| `POST /v1/computer/dictations` | `{operation_id, language, audio_wav}` |
| `POST /v1/computer/text` | `{operation_id, action, text, language}`; action is `rewrite` or `translate` |
| `DELETE /v1/computer/operations/<UUID>` | Cancels the caller's operation |
| `DELETE /v1/computer/session` | Revokes the caller's credential |

All routes except pairing require `Authorization: Bearer <session_token>`.
Dictation and text return
`{operation_id, transcript, text, rewritten, successful}`. Errors return a bounded
`{error}` code with a suitable HTTP status, without provider exception bodies.

`ready` retains its version 1 meaning: dictation configuration readiness.
The optional `action_readiness` object has three Boolean fields: `dictate`,
`rewrite` and `translate`. Each checks its own enabled workflow, model,
provider capability and personal credentials. A ChatGPT text route checks the
bound profile's local session permission and selected account identity.
These checks do not contact providers, discover models, refresh OAuth tokens,
or check Local Whisper installation. Actual provider processing retains its
credential and account checks. Text readiness does not depend on dictation.
The mobile connection displays the computer as available when at least one
action is ready. Explicit keyboard-session activation can support a text-only
workflow. Starting a recording still requires dictation readiness.

The host checks the requested action again at admission and against the frozen
configuration used for processing. Unknown actions are rejected. A mobile client
refreshes status before starting app text processing and checks the action at
the processing boundary. It rejects stale destinations and cancelled calls.
When an older host omits `action_readiness`, the mobile client uses `ready` for
dictation and keeps text actions unavailable. Partial or invalid capability
objects fail status validation; no hosted route is selected.

Audio is base64-encoded PCM16 mono WAV at 16 kHz, with a maximum duration of
300 seconds. The complete JSON request has a 16 MiB limit. The mobile converts
its recorded AAC clip before upload and removes its temporary WAV on every
terminal path. The computer owns its temporary input until processing ends.
Text input and each result text field have a 32 KiB UTF-8 limit, matching the
native history contract. Oversized results fail without truncation. The native
client accepts at most 512 KiB for a complete JSON response. This permits JSON
escaping of both valid result fields within their individual limits.

Remote operation IDs use [UUIDv7](https://www.rfc-editor.org/rfc/rfc9562.html#name-uuid-version-7)
and are scoped to the paired device. The native app creates one remote ID for
each explicit action and maps it to the existing local recording or text ID.
Cancellation and reply validation use that same remote ID. An identical retry
reuses a bounded stored result. Different content with the same ID is rejected.
An uncertain or expired operation must not automatically start expensive work
again. Cancellation and device revocation prevent a late result from being
published.

New IDs must have a timestamp within the previous two hours or the next five
minutes. SQLite schema 2 stores the greatest observed time before expired
metadata is removed. A restart or clock rollback cannot make a removed ID valid
again. Active claims remain protected. Existing schema 1 identity, devices and
legacy operation claims migrate without an identity reset; unknown UUIDv4
operation IDs cannot start new work.

The host retains at most 4,096 operation records. Expired inactive UUIDv7 claims
are removed automatically. `429 operation_limit` reports temporary capacity.
`409 operation_history_full` means retained legacy claims fill the store; the
user must revoke old device access on the computer to release those claims.
If the current device is revoked, it needs a new pairing. `409 operation_expired`
and `409 result_unavailable` require a new explicit action, rather than an
automatic upload with a new ID.
`400 operation_in_future` requires checking the date and time on both devices
before starting a new action.

The computer selects providers, models, prompts and its dictionary. The mobile
cannot supply provider credentials, arbitrary endpoints, file paths or tools.
Computer-scoped history must not enter account synchronization. Switching
destinations invalidates old operations and recording ownership. An unavailable
computer cannot silently select hosted processing. The computer identity owns
its iPhone history independently of network addresses. Pairing the same computer
after an address change preserves access to its existing records and deletion.

## Delivery evidence

This protocol describes the implementation boundary. It does not establish
Windows package acceptance, iPhone network acceptance, internet tunnel
availability or TestFlight availability. Those gates require evidence from the
exact delivered candidate.
