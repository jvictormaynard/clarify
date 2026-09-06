# Provider HTTP reliability and diagnostics

`provider_http.py` is the common transport policy for provider adapters. It
owns the HTTP connection lifecycle, connect/read timeouts, retry decisions, typed failures,
cooperative cancellation, redacted rotating logs, and diagnostic exports.
Provider adapters own request payload construction and successful response
parsing; they must not add a second retry layer or log request/response bodies.

## Connection lifecycle

The default client creates and closes a Requests session for each HTTP attempt.
It does not reuse idle TCP/TLS connections between desktop operations. This
prevents a stale connection retained from an earlier operation from breaking
the next transcription or text-generation POST. It also avoids sharing mutable
session state between concurrent desktop workers. TLS verification, proxy
handling, and request timeouts remain enabled. Explicitly injected sessions
remain the caller's responsibility.

Requests documents automatic connection reuse within a session in its
[advanced usage guide](https://requests.readthedocs.io/en/stable/user/advanced/#keep-alive).
The per-call session lifecycle is implemented by its
[request API](https://requests.readthedocs.io/en/latest/_modules/requests/api/#request).

This adds a connection/TLS handshake per attempt. An unauthenticated GET probe
to Groq on the affected Windows host measured about 0.6–0.8 seconds of added
latency compared with an open pooled connection. The probe did not reproduce
the production interruption at idle intervals up to 125 seconds. A local HTTP
integration test reproduces a server dropping a reused socket: the old pooled
client fails and the default per-attempt client succeeds. This establishes the
mechanism and the fix's coverage, not the remote cause of every historical error.

On September 5, 2026, local diagnostics recorded `ConnectionError` wrapping
`ProtocolError` for Groq text generation at 06:47:19 UTC. Usage records show a
local transcription completed at 06:47:08, a preceding cloud rewrite at
06:34:31, and a successful rewrite at 06:47:26. Thus this occurrence affected
cloud text generation after an idle interval, not local audio capture. The
older records lack the nested socket exception needed to distinguish a remote
close, reset, proxy, or another transport failure.

Optional dictation cleanup fails open: if cleanup cannot return usable text,
the already completed transcript proceeds through dictionary expansion and
publication. Cancellation still aborts the operation. A failed cleanup is not
reported as a successfully refined result. Standalone rewrite and translation
failures retain their error state and show a specific message in the pill.

## Timeout and retry policy

Timeouts are `(connect, read)` seconds:

| Operation | Timeout |
| --- | --- |
| Model discovery | `(3.05, 12)` |
| Credential validation | `(3.05, 12)` |
| Audio transcription | `(5, 90)` |
| Text generation | `(5, 60)` |

Only GET, HEAD, and OPTIONS requests are retryable by default. They use at most
three attempts for connection failures and HTTP 429, 502, 503, or 504. The
client honors `Retry-After` in seconds or HTTP-date form. Otherwise, it uses
exponential backoff starting at 250 ms with up to 25% jitter. Every delay is
capped at four seconds.

Discovery and validation therefore have a documented worst-case client budget
of 53.15 seconds: three `(3.05 + 12)`-second attempts plus two capped
four-second waits. Cancellation can end retry waits earlier.

Transcription and generation POSTs use one attempt. Without an idempotency key,
repeating them could duplicate billed work even when the first response was
lost. Authentication errors, invalid models, malformed requests, and all other
permanent failures also fail immediately.

## Error contract

The transport maps failures to typed exceptions:

- `AuthenticationError`
- `RateLimitError` and `QuotaError`
- `ProviderTimeoutError`
- `ServiceUnavailableError`
- `InvalidModelError`
- `InvalidRequestError`
- `InvalidResponseError`
- `ProviderCancelledError`
- `NetworkError`

Localized messages tell users what action to take. Safe diagnostics include the
provider, operation, HTTP status, and a locally generated operation ID. Provider
response bodies and headers are treated as untrusted: they are never included
in an exception, log record, diagnostic export, or interface message.

Cancellation is cooperative. Adapters pass a `CancellationToken`; the client
checks it before a request, after the response, and around retry waits. A result
received after cancellation raises `ProviderCancelledError` instead of being
returned to the caller. The underlying synchronous request cannot be interrupted
mid-socket; cancellation becomes effective at the next check or configured
timeout, while the UI immediately detaches from that request and ignores its
late result.

## Local logs and export

Provider errors are written as JSON lines to a rotating `provider.log`. The
default rotation is 512 KiB with three backups. Log records contain only
transport metadata: timestamp, provider, operation, method, host, attempt,
status, local operation ID, error type, selected retry delay, elapsed time,
connection policy, nested exception class names, and numeric OS error codes.
The URL path/query, headers, request/response bodies, audio path, source text,
transcript, and rewritten text are not logged.

`export_diagnostics()` creates a JSON file only when the user requests it. The
export contains application/runtime versions, coarse platform metadata, and
recent already-redacted error records. It does not contain configuration,
environment variables, credentials, URLs, audio, or user text. The recursive
redaction pass is applied again while exporting as defense in depth.

Remote telemetry and automatic upload are intentionally unsupported.
