# Shared computer byte relay primitives

This candidate includes a desktop connector, Host lifecycle integration and
QR-pinned iOS routes. It does not activate a public service. No domain, hosting
plan or certificate has been selected. The shared public build configuration
in `shared/computer_connect.json` keeps the relay disabled until deployment is
reviewed. Direct LAN access remains available.

## Transport and identity

The phone connects to `https://<namespace>.<relay-host>[:port]`. Its TLS session
ends at the existing desktop HTTPS backend. The namespace is the lowercase,
unpadded RFC 4648 Base32 encoding of SHA-256 of the desktop leaf certificate's
DER bytes (52 characters). The phone must verify that exact certificate pin.
The relay has no desktop private key and receives no phone bearer credential,
HTTP request, audio or text in plaintext. Network addresses, SNI, the public
desktop certificate, connection timing and byte counts remain visible.

The relay uses the standard library's `SSLObject`, `MemoryBIO` and SNI callback
to classify ClientHello. It reads at most 64 KiB within the handshake deadline.
For a namespace SNI, it discards the sniffer's output and forwards the original
input bytes, then the remaining TLS stream. It does not parse TLS records or
HTTP. For the exact root relay hostname, the same SSLObject switches to the
operator's server context and completes the public TLS handshake. Missing,
unknown or mismatched SNI fails closed. ECH without the visible route hostname
is not supported. A front proxy must pass raw TCP; TLS termination there would
break the phone's desktop identity.

The desktop makes separate, normally CA-validated TLS connections to the root
relay hostname for control and each data stream. Its backend destination is
always `127.0.0.1:target_port`. There is no arbitrary destination field or hosted
fallback. The outer data TLS carries the unchanged inner phone TLS bytes.

## Wire contract, version 1

Control frames are a four-byte unsigned big-endian length followed by at most
8,192 bytes of strict UTF-8 JSON. Duplicate keys, unknown fields, unknown kinds,
incorrect types and noncanonical encodings are rejected. All shapes include
exactly `v: 1` and `kind`, plus the fields below:

| Kind | Other fields |
| --- | --- |
| `challenge` | `nonce`: 32 random bytes, unpadded base64url |
| `register` | `certificate`: canonical padded base64 DER; `signature`: base64url DER ECDSA |
| `registered` | `namespace`: the certificate namespace |
| `open` | `pending`: 32 random bytes, unpadded base64url |
| `attach` | `pending`, `signature` |
| `attached`, `ping`, `pong` | None |

Each root TLS connection gets one fresh challenge. Registration signatures use
ECDSA P-256 with SHA-256 over these bytes, where `nonce` is the decoded 32 bytes:

```text
b"clarify-computer-relay\x00v1\x00register\x00" + relay_dns_ascii + b"\x00" + nonce
```

Attach signatures use the distinct `attach` purpose and append the decoded
32-byte pending ID after the fresh nonce. The DNS name must be canonical lowercase
ASCII without a trailing dot, wildcard, IP literal, path or port. Only P-256
certificate public keys are accepted. Certificates alone do not grant ownership.
The relay checks possession of the key; desktop certificate trust, expiry and
the exact leaf pin remain the phone/Host's responsibility.

A new valid registration replaces the old owner of the same namespace. Each
owner has a separate generation. Replacement or control disconnect cancels that
owner's pending and active streams. An old close cannot remove its replacement.
An attach needs the current owner's key, its fresh connection challenge and a
live pending ID in that generation. A successful proof consumes the ID once.
After `attached`, the data connection contains raw stream bytes with no framing.
The desktop only opens its loopback backend after that acknowledgement.

## Small APIs and lifecycle

`RelayIdentity(certificate_der, sign_callback)` accepts an existing desktop
identity. Its `proof()` method only passes canonical registration/attach
challenges to the callback and checks the returned signature. Callback exceptions
become `identity_proof_failed`; their contents are never logged.

```python
client = ComputerRelayClient(relay_host, identity, target_port, relay_port=443)
client.start()  # Starts one background worker; does not await TLS.
available = client.connected  # Thread-safe snapshot; status is a fixed string.
drained = client.stop(5.0)  # False means shutdown could not be confirmed.
```

The client owns its event loop, sockets and stream tasks. Reconnect uses capped
exponential delay and jitter; stop interrupts socket operations and retry sleep.
System DNS and the supplied signing callback run on the owned worker. Python
cannot cancel a blocked platform DNS call or callback. In that case `stop()`
returns false after its deadline, and `start()` refuses another worker. Keep the
object and retry shutdown once the blocked call returns. Do not report access
as disabled until shutdown is confirmed.

The default control context loads system CA roots, requires hostname validation
and TLS 1.2 or newer, and does not honor `SSLKEYLOGFILE`. An injected `ssl_context`
must retain those checks and contain only operator-approved public roots. The
caller must not mutate it during use. Private test roots use the separate
`fixture_ssl_context` option with a literal loopback `fixture_address`. Tests
retain CA and root hostname verification. No fixture option changes the local
backend destination. There is no production verification bypass.

`ComputerRelayServer(bind_host, port, relay_host, ssl_context, budget_path,
monthly_egress_cap, limits=Limits())` has async `start()` and `stop()`. Construct
and operate it on one event loop. `bind_host` is an explicit IP literal. Port
zero is available for owned tests. The public server context must contain the
operator's root-hostname certificate, require TLS 1.2 or newer and have no key
logging enabled. The server supplies its own SNI sniffer context. `status` exposes
aggregate counts and a fixed error code. The server aborts sockets on shutdown
and waits for all admitted connection tasks. Normal stream EOF closes both
directions after flushing pending writes; TCP half-close is not a separate
application protocol feature.

## Limits and budget

Default bounds are 64 registered hosts, 256 admitted TCP connections, 32 setup
handshakes, 64 pending streams, 128 pending/active tunnels and four streams per
host. A tunnel uses two relay TCP connections, in addition to the owner's control
connection, so the connection cap can apply first. One IP gets at most 32 open
connections and 60 admissions per minute. Global admissions are capped at 600
per minute; admission records have 1,024 IP slots and expire after one minute.
These limits can constrain multiple desktops behind one NAT.

Handshake and setup deadlines default to five and ten seconds. Control inactivity
has a 60-second limit. Tunnel inactivity has a separate 120-second limit on both
ends, covering the mobile client's 100-second processing request. Traffic in
either direction refreshes this tunnel deadline; blocked writes remain bounded.

When a server slot is reused while an older desktop child is still closing,
the client queues at most `min(streams_per_host, max_pending)` pending IDs.
Waiting and attachment share one setup deadline. Queue overflow or persistent
local capacity lag times out the new request without closing control or other
tunnels. Shutdown cancels queued admission and closing children.
Control heartbeat runs every 15 seconds. A control session rotates after 4,096
stream IDs instead of forgetting replay state. Invalid or excess opens close
the control session. Every path is bounded; there is no unbounded payload queue
or complete-request buffer. Pumps read at most 16 KiB and await the destination's
drain. asyncio, OpenSSL and the OS also hold bounded transport/socket buffers;
an asyncio reader can receive one transport chunk beyond its pause threshold.
Limits are validated before use. EOF, timeout, invalid proof, replacement,
control loss and stop release stream capacity.

The monthly egress cap is a required positive integer, in bytes. SQLite commits
aggregate reservations before socket writes, normally in 64 KiB leases shared
across all connections. A partial final lease can use the remaining allowance.
Unused lease bytes stay charged after shutdown or crash. No transaction runs
for each small packet. The stored cap must match the configured cap on restart.
Each UTC month has its own counter; a stored high-water month rejects clock
rollback. Multiple processes share the durable cap, but live ownership/routing
is process-local. Run one relay process per listener, without load balancing.

The database has an application ID and exact versioned schema. Foreign, empty
existing, malformed or newer-schema databases are refused. It stores only UTC
months, a cap and reserved-byte counters. It never stores addresses, certificates,
pending IDs, sessions, audio or text. Supply a dedicated local durable filesystem,
protect it against deletion/rollback, and preserve it across container replacement.
Deleting or restoring an older database defeats accounting. Do not use an
unrelated database, a shared network filesystem, or disposable container storage.

The meter includes bytes written from relay TCP streams, including encrypted
root control/data TLS, public TLS handshakes and raw inner TLS forwarded to the
phone. Sniffer alerts are discarded. TLS alert bytes written outside these
admitted paths, TCP/IP headers, retransmissions, kernel traffic, ingress,
connection floods, infrastructure and provider billing rules are outside this
meter. The byte cap is **not a provider quota or a cost guarantee**. A provider
spending limit and network-level admission rules are separate operator decisions.
Budget refusal closes remote paths and never enables hosted processing.

## Operator template

Use Python 3.12 and the existing pinned `cryptography` dependency. The service
requirements install only cryptography and its dependencies, constrained by the
root Linux lock. The Dockerfile pins the official `python:3.12-slim` OCI index
by digest. The index body matched the registry digest and included Linux amd64
when checked on 2026-10-27. A container build is still pending because Docker is
not available in this environment. The desktop package includes the client, protocol and
shared build configuration. It does not include the relay server.
Linux CI builds the relay image and runs its non-listening `--help` entrypoint.
The Dockerfile-specific context allowlist includes only its build files, the
Linux lock and the two relay server modules. It excludes local build outputs,
profiles, credentials and recordings.

The operator must supply root and wildcard DNS routing to the same listener,
a public CA certificate/key for the root relay hostname, certificate renewal,
a dedicated state directory writable by UID/GID 10001, a fixed monthly cap,
and network and hosting limits. The public certificate need not cover the
namespace: the phone sees the desktop certificate on that connection. Certificate
renewal requires restarting this primitive and will disconnect current streams.
No automatic provisioning, certificate purchase or DNS change is included.

The Compose template publishes only on `127.0.0.1`. It requires explicit values
for `RELAY_DNS_NAME`, `RELAY_CERT_DIRECTORY`, `RELAY_STATE_DIRECTORY` and
`RELAY_MONTHLY_EGRESS_CAP`. The certificate directory must contain `fullchain.pem`
and `privkey.pem`, readable by UID 10001. Build from the repository root with
`docker build -f connect/Dockerfile .`. Review `docker compose -f
connect/compose.yaml config` before any explicit start. No live key is bundled.
No public listener was started for this candidate.

The Host starts local HTTPS before its outgoing connector. Its automatic QR has
at most three priority LAN routes and one configured remote route. It can issue
a remote-only QR without LAN discovery and while the connector reconnects.
Explicit LAN route overrides preserve the previous contract. A failed or
unconfirmed connector stop closes and drains local processing, retains the
connector, and blocks restart and account changes until drain is confirmed.
Qt shows local and remote availability separately and retains failed startup
candidates through cleanup. No private key or relay URI enters a Settings snapshot.

Route limits, QR schema 1, exact desktop pins, no redirects, cancellation and
provider selection remain owned by their existing modules. The iOS build plugin
adds a scoped ATS exception only for the configured relay domain and its
subdomains. Global arbitrary-load exceptions are forbidden. Native ATS acceptance
is still pending. Loopback tests do not prove
Internet/4G/5G reachability, iPhone trust, production capacity, provider cost,
Windows package behavior, native builds or TestFlight availability.

Run the synthetic contracts with:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_computer_relay.py -v
```

The fixtures use temporary SQLite databases, generated CA/desktop keys, owned
ephemeral loopback listeners and a fake HTTPS backend. They make no provider call
and read no real profile, microphone, recording or application credential.
