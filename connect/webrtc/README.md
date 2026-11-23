# Computer WebRTC transport

This component adds a configurable internet transport. It does not start at
import, change LAN or tunnel configuration, or deploy a service. Processing
uses the existing paired-computer credential and UUIDv7 operation contract.
There is no provider API, recorder, or inference implementation here.

## Integration contract

1. The account service supplies `Control(account_validator, turn_secret=...,
   turn_urls=...)`. The validator receives the complete Authorization header.
   It must validate the account on each call and return a stable issuer/subject
   string. Invalid, expired, or revoked sessions must raise. No caller-supplied
   account identity is accepted. Serve `signaling_server(address, control)`
   behind HTTPS with an authenticated request rate limit. Do not expose the
   loopback acceptance fixture. Pass `database=...` to retain bounded account enrollment and revocation in
   SQLite. Tickets remain in memory and expire on restart. The operator entry
   point requires a database path. `AccountValidator` provides a read-only
   adapter for the existing `/v1/account` endpoint: it maps the signaling Bearer
   token to `X-Session-Token`, rejects redirects and scopes identity by origin.
   It performs no login, refresh, provider setup or account mutation. An explicit
   entry point is available:

   ```sh
   python -m connect.webrtc --account-origin https://ACCOUNT_ORIGIN \
     --turn-secret-file /PRIVATE/turn-secret --turn-url turns:TURN_HOST:5349 \
     --database /PRIVATE/webrtc.sqlite3 --port 48763
   ```
2. After explicit device approval, enroll a P-256 public JWK under an account
   and host ID. Save that key on the phone during trusted pairing. The computer
   keeps the private JWK in its secret store. The client must pass the **saved**
   public key to `connectComputer`; the key returned by signaling is discovery
   data and must not replace that pin. A signed answer binds the host ID,
   ticket, DTLS fingerprint and full answer SDP.
3. Electron main calls `startComputerWebRTC` from `webrtc-host.cjs` after the
   existing personal host starts. Pass Electron's `BrowserWindow`, `ipcMain`,
   and `session`, plus `host`, `privateJwk`, `signal(action, fields)`, and
   `dispatch(value, ticket)` and `closePeer(ticket)`. The new hidden renderer has no Node or microphone access.
   Its private IPC handler accepts only its own main frame. `signal` retains
   the account session in main. `dispatch` forwards bounded frames through the
   trusted Python pipe to `ComputerBridge`. Calls must run concurrently on
   workers so DELETE cancellation can pass a waiting inference. Stop this
   owner before account transitions, host shutdown, or provider shutdown.
   Keep one Python bridge per ticket and call its `close()` from `closePeer`.
   `qml_computer` wraps the personal host with `WebRTCHost`; `qml_electron`
   drains its private-pipe messages after the computer controller is bound.
   `host.cjs` creates and stops the hidden peer through `webrtc-main.cjs`.
   Set `CLARIFY_WEBRTC_SIGNAL_URL` to the exact HTTPS `/signal` URL to enable
   remote setup. No default endpoint exists. A signed-in account is required
   for this remote setup; LAN pairing still works without an account.
   The private JWK extends the existing protected `clarify_computer` identity.
   The explicit QR includes only its public key and the configured signal URL.
   New hosts do not start a Cloudflare tunnel.
4. For normal RPC, `dispatch` calls `ComputerBridge.request(value)`.
   The envelope is `{method,path,authorization,body}`. The response is
   `{status,body}`. Pairing and remote-registration requests are forbidden on
   this transport. Every processing call rechecks the existing device token.
   Cancellation uses the existing DELETE operations route and UUID, including
   cancellation before admission. No new operation ID is created by transport.
5. For recognition sessions, dispatch envelopes with `recognition` to
   `ComputerBridge.recognition(authorization, recognition, operation_id, body)`.
   `start` accepts dictation metadata without `audio_wav`; `feed` accepts
   `{sequence,data}` with contiguous zero-based sequence and base64 WAV-file
   bytes; `finish` passes the assembled WAV to the existing dictation route;
   `cancel` uses the existing cancellation tombstone. The default is a bounded
   upload adapter, **not streaming recognition**. An injected adapter can
   replace this branch. A recognizer must reserve once-only admission before
   inference, reuse its cancellation token, and publish through the existing
   host's revocation and result checks. It must not infer again after an
   uncertain finish. `close()` cancels unfinished uploads. One bridge per peer
   must receive close/disconnect notification from the application owner.
6. The containing app saves the QR's optional WebRTC binding in its private
   Keychain credential. `ClarifyWebRTCSignalURL` in the app's Info.plist must
   match that URL exactly. A QR cannot select an arbitrary signaling service.
   On refresh, a signed-in app can open `ComputerWebRTCEngine`, a hidden
   WKWebView with bundled Clarify data-channel JavaScript. Native app code
   performs bounded signaling with its captured account session. The page has
   no account credential, network fetch, microphone access or keyboard bridge.
   The signed answer must verify against the QR-pinned public key. An uncertain
   processing response is never replayed. Without configured authenticated
   WebRTC, the existing pinned HTTPS route remains available.
   CocoaPods and Swift Package resources explicitly bundle the engine assets.
   After editing the shared RTC modules, run `python -m connect.webrtc.bundle_ios`;
   `python -m connect.webrtc.bundle_ios --check` verifies the shipped bundle.
   Apple SDK compilation, physical-device behavior and background acceptance
   remain open; Linux source checks do not prove those properties.

## Live recognizer injection

`ComputerBridge(host, recognition_handler=handler)` can replace only the
recognition branch. The handler receives `(authorization, action, operation_id,
body)` and returns the same `{status,body}` envelope. The default stays buffered
WAV upload and invokes the existing once-only processing pipeline.

`live.LiveRecognition` adapts the supplied engine's `open_live_session`, `feed`,
`finish` and `cancel` methods. It accepts contiguous PCM16 mono 16-kHz frames of
up to 80 ms, at most 300 seconds, with a 30-second finish deadline. Partials are
cumulative display-only snapshots, bounded to 32 KiB. Feed overflow cancels and
fails. Finish caches its final result in the adapter and never repeats inference.
The caller supplies the shared cancellation event and an **already durably
admitted** operation. Admission must happen before constructing this adapter.
The composition root can set
`runtime.computer.webrtc.recognition_factory = factory` before enabling hosting.
The factory receives `(host, ticket)` and returns a callable handler with the
four arguments above. Its `close()` must cancel all peer-owned live claims.
The handler must use the host owner's durable admission and publication APIs;
transport does not grant permission to publish a final result.
The Qt composition root attaches `computer_live.ComputerLivePeer`. It uses the
shared `ComputerHost` admission and execution owners before it selects or opens
an engine. The frozen dictation workflow receives the final raw transcript as
trusted pretranscribed input and does not run recognition again. Cancellation,
revocation and peer close use the same durable operation claim and publication
barrier as WAV processing. Unsupported speech routes return `live_unsupported`;
they do not switch providers.

For this handler, `start` accepts ordinary dictation metadata without audio;
`feed` accepts contiguous zero-based `{sequence,data}` frames containing base64
PCM16 mono at 16 kHz, at most 2560 bytes per frame. A feed can instead contain
`{frames:[{sequence,data},...]}`, with one through eight contiguous frames. A
sender can drain queued frames in one serialized request without waiting for a
full batch. This keeps capture independent of an individual 80-ms round trip.
The acknowledgement contains the last accepted sequence. Feed replies include
`partial` only when its cumulative text changes; clients retain the preceding
snapshot when that field is absent. An explicit `partial` read returns the latest
snapshot. `finish` requires the captured PCM's `sha256` and `bytes`.
It checks retained bytes, immutable frames accepted by the native queue, and the
native consumed-duration receipt. The native API does not export a separate hash
of consumed memory. Duplicate finish reads the host result cache. A failed or
uncertain session never starts another recognition pass automatically.
Actual native-model replay over direct and forced TURN is available through the
harness below. This is separate from physical-phone and native capture acceptance.
The engine remains owned by the ASR service; this adapter never selects,
downloads or shuts down the shared engine.

## Bounds and failure behavior

Unanswered setup tickets expire after 120 seconds. After an answer, authenticated
polls renew a 90-second idle lease, with 8 sessions per account and 1024 total.
SDP messages are immutable once submitted. TURN credentials use coturn's
HMAC-SHA1 REST scheme with a 15-minute expiry. Native status preparation replaces
an aging connection before a new operation after five minutes, leaving time for
capture and finalization. Existing processing is never replayed on that connection.
Host or account revocation closes peers at the next authenticated poll. Terminal
channel closure immediately retires the host bridge and notifies native code.
The phone retains an old transport only for bounded cancellation or revocation,
then closes it. The keyboard never receives those credentials.
A production operator must also bound admission at ingress. Issued TURN passwords
remain usable until expiry; host revocation does not retroactively revoke them.

The ordered reliable channel uses 48-KiB wire frames, 16-MiB assembled bodies,
8 incomplete messages, 8 executing RPCs and 4096 message IDs per connection.
Incomplete bodies expire after 15 seconds. Send buffering is bounded with a
10-second deadline. RPC timeout or disconnect reports `response_uncertain`
and never replays the call. A caller may query or explicitly retry the same
operation ID under the existing host's replay contract; it must never mint
an ID to hide uncertainty.
Recognition uploads have two concurrent slots, a 300-second lifetime,
4096 chunks and 9,600,044 bytes per session. The recorder remains app-only.

## Reproduce on Linux

Use the repository's pinned Python environment, `npm ci --ignore-scripts` in
`desktop/`, Docker, and `/usr/bin/google-chrome`. Run from the repository root:

```sh
python scripts/run_tests.py tests.integration.test_computer_webrtc_transport tests.integration.test_computer_webrtc_lifecycle -v
node --test desktop/scripts/electron.test.cjs
node connect/webrtc/e2e.mjs /tmp/clarify-webrtc-acceptance
# Also exercise the real Electron host factory (requires Xvfb and Electron binary):
node desktop/node_modules/electron/install.js
node connect/webrtc/e2e.mjs /tmp/clarify-webrtc-electron-acceptance --electron
```

For a public-clip replay through the product native engine, explicitly set
`CLARIFY_WEBRTC_LIVE_WAV` to a mono 16 kHz PCM16 WAV and
`CLARIFY_WEBRTC_LIVE_ASSETS` to the verified model/runtime asset directory. Add
`--electron` for the real hidden Electron peer and private application pipe.
These variables affect only the isolated harness. They do not configure a user
profile or enable a production service.

The harness creates an isolated host and authenticated loopback signaling
and bridge listeners. It starts coturn 4.6.3 by immutable digest, with generated
credentials, a 128-MiB memory limit, half a CPU, 16 allocations, and loopback
ports 54879 and 54900–54930. These ports must be unused. It changes no firewall,
proxy, certificate or profile. Its `finally` block closes browsers, the Python
process and its named container. Evidence includes raw ICE candidate-pair and data-channel
statistics, setup and RTT samples, a screenshot, a WebM recording and idle
resource samples. Traffic counters sum WebRTC candidate-pair bytes across candidate changes; they
exclude signaling HTTP, test bridge HTTP, Ethernet headers and provider traffic.
Docker host-network `NetIO=0` is not a traffic measurement. No cost estimate is
inferred from these counters. These are local Chromium peers, not mobile or
cellular measurements. The browser RSS sum includes the test page and video
capture processes and is not a desktop product memory estimate.

`compose.yaml` supplies an inactive TURN deployment profile. It requires an
operator-controlled public interface, realm, secret and TLS certificate files.
Production denies loopback and private peers; only the isolated harness permits
loopback. No Railway deployment or tunnel per user is used.

## Open native acceptance

On macOS/iOS, compile the supplied containing-app engine and capture integration.
Incremental capture is disabled unless the containing app explicitly sets
`ClarifyExperimentalLiveCapture=true`, and admission also requires foreground state.
Enable that path only after background recording and keyboard acceptance. The
ordinary WAV path remains the default. The keyboard must not load the RTC engine. Verify saved-key mismatch, account and device revocation,
background/suspend cleanup, cancellation during upload and inference, repeated
finish with the same operation ID, direct Wi-Fi and forced TURN, large WAV
backpressure, and network loss after admission. Verify that the keyboard cannot
read account, computer or TURN credentials. Run physical-device cellular and
NAT-change tests separately. On Windows, test the packaged shell and account/shutdown lifecycle.
These gates remain open until there is direct evidence.

Official references checked for this implementation:
[WebRTC API](https://www.w3.org/TR/webrtc/),
[coturn options and REST authentication](https://github.com/coturn/coturn/blob/master/README.turnserver).
No new application runtime dependency was added.
