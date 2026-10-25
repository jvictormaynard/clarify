# Clarify privacy notice

Effective date: 25 October 2026.

Clarify is an open-source app maintained by João Victor Maynard Mota. This
notice describes the optional hosted beta at `clarify-api.victormaynard.com`
and the Clarify desktop and iOS clients. Self-hosted services have their own
operators and policies.

## Choose how to process your audio

- Without an account, a personal provider key sends audio and text directly
  to the selected provider. The Clarify account service does not receive them.
- Desktop local inference processes audio on the device. It does not silently
  switch to a cloud provider. Local inference is not available on iOS.
- When you sign in, account processing is active automatically. The Clarify
  service receives audio and the vocabulary needed for that request. It sends
  audio to Groq for transcription,
  then sends the transcript and vocabulary to Groq for rewriting. The result
  returns to the device.

Signing in automatically synchronizes the account dictionary and new account
transcriptions, including their original and revised text, timestamp and source
device. An offline copy remains on each signed-in device. Pre-upgrade history,
transcriptions made without an account, guest snippets and personal provider keys
remain on the original device and are not uploaded. Snippets created while signed
in synchronize with that account. Guest snippets are not imported automatically. Choose Continue without an
account to keep vocabulary and history local. Earlier app versions do not
synchronize history.

## Account information and security

The service stores the email address, verified account status, sessions,
account dictionary, account snippets, synchronized history, and processing usage
needed to enforce limits. It also stores the date of requested hosted access and
the most recent hosted activity to determine weekly allocation eligibility.
Resend delivers the email codes. Enter the code in the app; the email does not
require a browser link. Codes expire after 10 minutes. Sessions expire after
14 days and can be revoked by signing out.

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

Desktop maintainer experiments can explicitly enable local benchmark audio
collection. It is disabled by default and separate from account history. When
enabled, normal stopped recordings retain a local WAV copy, limited to 64 MiB
per clip and 256 MiB in total. The next app start or archive access removes
copies older than seven days; removal cannot run while the app is closed.
These copies do not synchronize or upload automatically. A separate explicit
benchmark command can send selected copies to the configured test provider.

Uploaded audio uses temporary files removed at the end of request processing.
An interrupted process can leave temporary files until its container is removed.
The server caches results for five minutes to avoid charging twice for a retry;
periodic cleanup removes expired text. Operation metadata is kept for 31 days.
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
This removes the account, hosted dictionary and snippets, synchronized history and its local
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
Personal-key providers and custom endpoints have their own terms.

For privacy requests, contact the maintainer through the links on
[the maintainer's profile](https://github.com/jvictormaynard). Establish a
private channel before sharing account details. Do not post email codes,
provider keys, recordings or private transcripts in public issues.
