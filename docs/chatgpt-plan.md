# ChatGPT plan on desktop

Clarify's personal desktop mode can use a ChatGPT subscription for text tasks.
It is separate from a Clarify account and from an OpenAI API key. Sign-in does
not change workflow providers. Select ChatGPT explicitly for each text workflow.
Signed-in Clarify users keep Clarify-managed processing and do not see personal
provider controls.

## Connect and select a model

Open **Settings → Models and services**, select **ChatGPT (subscription)**, then
select **Continue with ChatGPT**. Finish sign-in in your system browser. Allow
plan use when OpenAI asks. A connected identity without that permission cannot
run text requests. The first plan connection shows a dismissible notice. Its
acknowledgement is saved in the protected account registration, outside config
drafts. See the [OpenAI UI guidance](https://developers.openai.com/siwc/ui-ux-guidelines).

Open **Text**, select a workflow, then select ChatGPT and a model. Model names
and order come from that account's catalog. Unknown catalogs are empty. Custom
model IDs and endpoints are unavailable on this route. Add or switch saved
accounts in Models and services. Switching accounts or signing out clears old
model selections; select an available model again.

Text is sent to OpenAI. Eligible Plus and Pro plans use their existing limits;
connecting does not create another allowance. For Plus, usage shares the
five-hour limit across apps. That five-hour limit does not apply to Pro. Open
**Manage usage in ChatGPT** to review your account and app limits. See
[accounts and sessions](https://developers.openai.com/siwc/token-sharing-open-source/profiles-and-sessions).

This provider handles text only. Audio capture and transcription need a separate
provider, such as Local Whisper. The plan flow does not support the transcription
API. See [preview limits](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations).
An auth, permission or quota failure stops the ChatGPT request. It never starts
a request billed to a personal API key or to Clarify. See
[errors and recovery](https://developers.openai.com/siwc/token-sharing-open-source/errors-and-recovery).

## Direct OAuth and inference

The direct open-source flow uses dynamic client registration, PKCE, fresh state
and nonce, and a loopback listener at `http://127.0.0.1:<port>/auth/callback`.
The listener starts before the browser. Each attempt uses the same exact callback
URI for authorization and code exchange. Plan permission is optional. The auth
service validates identity and granted scopes, retains each issued client ID,
and owns protected credentials. See
[registration and sign-in](https://developers.openai.com/siwc/token-sharing-open-source/sign-in).

The provider sends OAuth bearer credentials to `GET https://api.openai.com/v1/models`
and `POST https://api.openai.com/v1/responses`. Inference uses `store=false` and
`stream=true`. Model slugs remain request IDs; server display names are UI labels.
See [models and inference](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference).
There is no Codex app-server dependency.

The Qt controller receives an injectable session for isolated tests. Production
resolves the session from the configuration profile directory. React receives
only connection, plan-permission, account-list, notice, generation, busy and safe
error fields. It receives no tokens. Commands are allowlisted. The usage action
opens only `https://chatgpt.com/settings/usage`. The session owns authorization
URLs. Workers publish through a controller-owned mailbox. Cancellation, session
identity and shutdown checks reject obsolete results.

Refresh tokens rotate. Only the auth service reads and replaces them; Settings
does not copy them or keep a second credential cache. See the
[token reference](https://developers.openai.com/siwc/token-sharing-open-source/token-reference).

## Self-hosted VM boundary

OpenAI documents a local OAuth flow followed by secure credential transfer to
the same tool/client on a VM for the same user and workspace. A browser's
`127.0.0.1` callback cannot reach a remote VM. The VM needs its own persistent
host ID. Preserve that ID during transfer and let one runtime own the rotating
refresh session. See [self-hosted VMs](https://developers.openai.com/siwc/token-sharing-open-source/self-hosted-vms).

Clarify currently provides the desktop connection flow. It does not provide a
credential export/import command or a supported VM credential-transfer tool.
Windows current-user DPAPI ciphertext cannot simply be copied to another user
or computer. Do not copy desktop secret-store files as a VM setup procedure.
Hosted Clarify and mobile account processing do not use this personal session.

## Validation boundary

Offline Qt and browser tests use synthetic accounts, model catalogs and a
temporary profile. They do not open real OAuth, use provider credentials, access
a microphone or call OpenAI. Native Windows browser handoff and authenticated
end-to-end acceptance remain integration checks before publication.

OpenAI's [overview](https://developers.openai.com/siwc/token-sharing-open-source)
owns the client/host terminology and current availability. Source facts were
checked on 2026-10-26; account eligibility remains subject to OpenAI policy.
