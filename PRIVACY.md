# Clarify privacy notice

Source notice updated: 16 November 2026. Deployment of this source is a separate step.

Clarify is an open-source app maintained by João Victor Maynard Mota. This
notice describes the optional account service at `clarify-api.victormaynard.com`
and the Clarify desktop and iOS clients. Self-hosted services have their own
operators and policies.

## Choose how to process your audio

- Desktop local inference processes audio on the computer. It does not silently
  switch to a cloud provider. Signing in does not change this route.
- A personal provider key sends audio or text directly to the selected provider.
  The Clarify account service does not receive this processing input.
- A connected eligible ChatGPT subscription can rewrite, translate or refine text.
  Source text, instructions and applied vocabulary or snippets go directly to
  OpenAI. This route sends no audio and grants no access to conversations or memories.
- OpenCode runs on the user's computer with a separate local configuration. Its
  selected free provider receives the text needed for that operation. Free access
  has provider limits. A refusal does not select a paid provider automatically.
- On iPhone, processing uses an explicitly paired computer. The computer uses its
  own models and provider settings. Computer history stays on the iPhone and does
  not synchronize with a Clarify account. Optional on-device Apple speech source
  remains disabled until native acceptance.
- Clarify-funded transcription and text processing are retired. Legacy endpoints
  reject requests with an update-required error before reading processing input
  or calling a provider. An account alone does not enable mobile processing.

Signing in automatically synchronizes the account dictionary and new account
transcriptions, including their original and revised text, timestamp and source
device. An offline copy remains on each signed-in device. Pre-upgrade history,
transcriptions made without an account, guest snippets and personal provider keys
remain on the original device and are not uploaded. Snippets created while signed
in synchronize with that account. Guest snippets are not imported automatically. Choose Continue without an
account to keep vocabulary and history local. Earlier app versions do not
synchronize history.

## Paired computer access

The camera reads a one-use QR inside the iOS app. This code expires after five
minutes. The app uses it to obtain its own revocable device credential. The
credential and trusted computer routes remain in the containing app's Keychain;
they are not shared with JavaScript or the keyboard extension. The computer's
private TLS identity uses the desktop credential store. Its local database stores
paired-device names, token hashes and operation metadata. Result text remains in
a bounded memory cache and is discarded when the host stops.

Desktop access is off until you enable it. Startup access needs a separate
explicit choice. You can revoke a paired device or stop access in General
settings. The direct LAN route requires the devices to share a reachable local
network and uses the certificate fingerprint supplied by the QR. An unavailable
computer does not silently switch processing to the hosted service. Temporary
audio is removed after normal processing; a crash or forced shutdown can leave
files until they are removed. Deleting the executable does not delete the profile.

When a remote relay is configured, it forwards encrypted traffic between the
iPhone and computer. The TLS session ends at the computer. The relay receives no
audio, text or device credential in plaintext. Its operator can see network
addresses, the computer's public certificate and route, connection times and
traffic volume. The included relay saves aggregate monthly byte-budget counters;
it does not save device credentials, desktop certificates, audio or text.
This optional TLS relay does not require a Clarify account. It remains disabled
in builds without a configured relay service.

New internet connections use WebRTC, directly when possible or through a TURN
relay. A verified Clarify account authorizes signaling and short-lived relay
access. Device credentials still authorize processing. Trusted pairing saves the
computer's public key; signaling cannot replace it. The signaling operator stores
bounded host enrollment and revocation metadata. Audio and text travel inside the
encrypted peer connection. The TURN operator can see network addresses, connection
times and traffic volume. Account sessions stay in native code, outside the
hidden transport page and keyboard extension. New hosts do not allocate Cloudflare
tunnels. Existing stored routes and their compatibility modules remain readable.
Internet access stays disabled without an operator-configured signaling endpoint.

## Account information and security

The service stores the email address, verified account status, sessions,
account dictionary, account snippets, action definitions and synchronized history.
Historical processing and funding records remain for accounting; new processing
does not consume a Clarify inference allocation.
Resend delivers the email codes. Enter the code in the app; the email does not
require a browser link. Codes expire after 10 minutes. Sessions expire after
14 days and can be revoked by signing out.

You can also sign in or create an account with Google, Microsoft or GitHub.
The selected provider receives the sign-in request in your system browser.
Clarify receives the provider account identifier, email address and basic
profile information needed to identify the account. Clarify does not receive
your provider password and does not request access to repositories, files or
contacts. Provider access tokens are not stored. The Clarify session stays in
the client's credential store; it does not appear in browser callback URLs.
An email address that the provider has not verified requires an email code.
Accounts with the same email address are not linked automatically.

The separate ChatGPT plan connection stores the verified OpenAI account
identifier, email, client registration, host identifier, and OAuth credentials
in a separate `chatgpt-secrets` desktop credential store. Windows protects this
record with current-user DPAPI. Experimental Linux and macOS source runs use the owner-restricted
file backend. Tokens are not sent to the Clarify account service or Settings web
interface. Signing out clears the selected connection's tokens and attempts to
revoke its renewable session. If revocation cannot be confirmed, disconnect the
app in ChatGPT settings. Retained account registrations allow later sign-in;
signing out does not delete the OpenAI account.

To prevent abuse, the service stores hashes derived from IP addresses or account
IDs, plus request counters and expiry times for rate-limit windows. These IP and
account rate-limit records expire within two hours. Periodic cleanup removes
expired records.

The service uses HTTPS and a private PostgreSQL database hosted on Railway.
Snippet triggers are replaced after recognition and before optional rewriting.
Applied saved text is sent to the rewrite provider as part of the source message;
the model can adjust its wording and formatting. Only enabled trigger phrases
can be sent as recognition or vocabulary hints. A standalone trigger inserts its
exact saved text without a rewrite request. Substituted text can appear in
synchronized transcription history; the original recognized transcript is retained.

Authorized service operators can access server data; dictionary, snippet and history sync are not
end-to-end encrypted. Windows protects stored keys and account sessions with
current-user DPAPI. iOS stores credentials in Keychain. Desktop source runs on
Linux and macOS use owner-restricted credential files and are experimental.

## Retention and deletion

Desktop stopped recordings keep a full local audio copy in the profile's
`recording-recovery` folder, including failed processing attempts. History lists
these recordings even when text history is disabled. They remain until you delete
the corresponding History item. They do not synchronize with account history. Retry sends
the selected audio through the current personal provider settings as a new
request. Cancelled recordings are not added. A crash during capture, before the
local copy is saved, can leave only the working file. History can also find
remaining working files after processing ends or the app restarts. A full disk
can prevent either copy from being saved.

iPhone stopped recordings remain in the app's private Application Support
storage until explicit deletion from a History item in Dictation. Audio is excluded from device
backup and is not synchronized with account history or shared with the keyboard.
Reprocess uses the paired computer as a new request. Clearing
text history does not delete recordings. An interrupted capture or a failed
storage move can leave a working clip in temporary storage; recovery can list
that clip while it remains available. iOS can remove temporary storage, and a
forced termination during capture can leave an incomplete recording.

Playback and audio export read the local recording. Undo AI edit changes the
text shown on this device to the original transcription; it leaves the account's
stored text unchanged. Deleting an item removes its local audio and deletes its
text under the existing local or account history policy. Clearing text history
leaves local audio as items that can still be played, exported or retried.

Desktop maintainer experiments can explicitly enable local benchmark audio
collection. It is disabled by default and separate from account history. When
enabled, normal stopped recordings retain a local WAV copy, limited to 64 MiB
per clip and 256 MiB in total. The next app start or archive access removes
copies older than seven days; removal cannot run while the app is closed.
These copies do not synchronize or upload automatically. A separate explicit
benchmark command can send selected copies to the configured test provider.

Computer processing uses temporary audio files removed after normal processing.
A crash or forced shutdown can leave temporary files. The computer keeps a bounded
in-memory result cache and durable operation metadata for duplicate and cancelled
request handling. The account service receives no new inference uploads. Historical
server processing caches and operation records retain their existing cleanup policy.
Synchronized account history is stored separately until you delete entries,
clear account history, or delete the account. Deletion removes stored transcript
text and retains only a record identifier and synchronization revision so an
offline device cannot restore a known deleted entry. Account deletion removes
these synchronization records too. Local caches preserve pending changes when
offline and synchronize automatically when the app can reach the service.
Monthly aggregate budget counters are retained for accounting and abuse control.
Weekly accounting records remain for financial reconciliation. Account deletion
detaches them from the account. Financial records do not contain transcript text.
Application logs exclude audio, transcripts, credentials and request headers.
Hosting and provider services can retain their own connection and usage metadata.

Use the account controls in Settings / Ajustes to delete the account and confirm.
This removes the account, synchronized dictionary and snippets, synchronized history and its local
cache on the device performing deletion, clears processing text and content
hashes, and detaches processing accounting records. It does not erase guest or
pre-upgrade local history. Clear local history separately in the app. Daily database
backups can retain deleted data for up to six days before rotation. Restoring
a backup requires reapplying subsequent deletion requests.

## External services and contact

The public financial page shows amounts, dates and neutral movement categories.
It excludes account and donor names, email addresses, operator references,
payment identifiers and bank details. Stripe is not connected. A future
read-only Stripe connection can publish normalized balances and movements,
separated by currency. It does not expose a private dashboard or API key. A
verified payment link, if enabled later, opens Stripe's own payment page.

Provider terms apply to data sent to them. Groq can retain request data for
reliability and abuse investigations under its own policy; do not assume that
deleting a Clarify account deletes provider records. Read
[Groq's data policy](https://console.groq.com/docs/your-data),
[Railway's privacy policy](https://railway.com/legal/privacy), and
[Resend's privacy policy](https://resend.com/legal/privacy-policy).
Social sign-in also follows the selected provider's privacy policy:
[Google](https://policies.google.com/privacy),
[Microsoft](https://privacy.microsoft.com/privacystatement), or
[GitHub](https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement).
Personal-key providers and custom endpoints have their own terms.
ChatGPT plan processing follows the connected account's OpenAI terms and
settings. Requests set `store: false`; this does not promise that OpenAI retains
no connection or usage data. Review the
[ChatGPT plan integration guide](https://developers.openai.com/siwc/token-sharing-open-source).

For privacy requests, contact the maintainer through the links on
[the maintainer's profile](https://github.com/jvictormaynard). Establish a
private channel before sharing account details. Do not post email codes,
provider keys, recordings or private transcripts in public issues.
