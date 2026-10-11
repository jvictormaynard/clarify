# Clarify privacy notice

Effective date: 11 October 2026.

Clarify is an open-source app maintained by João Victor Maynard Mota. This
notice describes the optional hosted beta at `clarify-api.victormaynard.com`
and the Clarify desktop and iOS clients. Self-hosted services have their own
operators and policies.

## Choose how to process your audio

- Without an account, a personal provider key sends audio and text directly
  to the selected provider. The Clarify account service does not receive them.
- Desktop local inference processes audio on the device. It does not silently
  switch to a cloud provider. Local inference is not available on iOS.
- With hosted processing enabled, the Clarify service receives audio and the
  vocabulary needed for that request. It sends audio to Groq for transcription,
  then sends the transcript and vocabulary to Groq for rewriting. The result
  returns to the device.

History and snippets remain on each device in this version. Signing in
automatically synchronizes the account dictionary so it is available on another
device. Choose Continue without an account to keep vocabulary on the device.
Personal provider keys are not synchronized.

## Account information and security

The service stores the email address, verified account status, sessions,
account dictionary, and processing usage needed to enforce limits.
Resend delivers the email codes. Enter the code in the app; the email does not
require a browser link. Codes expire after 10 minutes. Sessions expire after
14 days and can be revoked by signing out.

The service uses HTTPS and a private PostgreSQL database hosted on Railway.
Authorized service operators can access server data; dictionary sync is not
end-to-end encrypted. Windows protects stored keys and account sessions with
current-user DPAPI. iOS stores credentials in Keychain. Desktop source runs on
Linux and macOS use owner-restricted credential files and are experimental.

## Retention and deletion

Uploaded audio uses temporary files removed at the end of request processing.
An interrupted process can leave temporary files until its container is removed.
The server caches results for five minutes to avoid charging twice for a retry;
periodic cleanup removes expired text. Operation metadata is kept for 31 days.
Monthly aggregate budget counters are retained for accounting and abuse control.
Application logs exclude audio, transcripts, credentials and request headers.
Hosting and provider services can retain their own connection and usage metadata.

Use the account controls in Settings / Ajustes to delete the account and confirm.
This removes the account and its hosted dictionary, clears cached text and
content hashes, and detaches processing accounting records. It does not erase
local device history. Clear local history separately in the app. Daily database
backups can retain deleted data for up to six days before rotation. Restoring
a backup requires reapplying subsequent deletion requests.

## External services and contact

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
