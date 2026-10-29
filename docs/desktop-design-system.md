# Desktop design system

The React/Tauri Settings window uses the approved T3 Code dark design and shared
React controls. Its workspace includes dictation, style, text actions, dictionary,
snippets and history. Application preferences and account access use a Settings
dialog. The Qt/QML pill,
quick menus and launch-failure Settings fallback retain their own theme and
behavior. Mobile and the server are outside this system.

## Required use

This guide is the sole visual specification for React/Tauri desktop pages and
controls, including new pages. Read it before any desktop visual change. Apply
the standard within authorized UI work even when the request has no prior
conversation or does not repeat the style requirement. Routine work that follows
this standard does not need another style approval.

Inspect the current tokens, shared controls and an existing page for the same
type of content before editing. Compose new pages from those owners. Matching
colors in separate page controls is not sufficient. Keep visual metrics here;
update the shared implementation and this guide together when the standard
changes. Do not create another style guide or copy the metrics into `AGENTS.md`.

For Qt/QML work, preserve the native theme, shell, passive pill focus and existing
interaction contracts. Do not apply Settings panels, dialogs or popup geometry
to the pill or its quick menus.

## Source reference

The reference is [T3 Code at `5eebf77b373b`](https://github.com/pingdotgg/t3code/tree/5eebf77b373b719ca4456985340707afa267310e),
checked on 29 October 2026. Its design overhaul and Settings reorganization are
on `main`: [#24865](https://github.com/pingdotgg/t3code/pull/24865),
[#25324](https://github.com/pingdotgg/t3code/pull/25324) and
[#25651](https://github.com/pingdotgg/t3code/pull/25651).
[#25778](https://github.com/pingdotgg/t3code/pull/25778) has also merged, so the
new design is the only design. The refresh includes the shared sidebar geometry
from [#22287](https://github.com/pingdotgg/t3code/pull/22287).
The copied source and local Inter font retain their license
texts and exact provenance in `desktop/licenses/source-components.json`.

The pinned source and the local reference screenshots below define the approved
style. The source check included development and staging branch names, recent
Settings and redesign PRs, and the changes since the previous reference
`0b02b21e5a45`. The relevant Settings design is already on `main`. Open PRs
[#26708](https://github.com/pingdotgg/t3code/pull/26708) and
[#26716](https://github.com/pingdotgg/t3code/pull/26716) propose further menu
motion changes; they are outside this reference. Routine UI work does not
require a newer upstream checkout. Later T3 changes do not change this standard
automatically.

T3's `SettingsSidebarNav`, `WorkspacePageContainer`, `SettingsGroup`,
`settingsLayout` and `components/ui` define the navigation, page, form and
control geometry. Clarify uses these rules in its standalone Settings window.
Its native titlebar replaces T3's modal close header. It does not create a
second application shell behind the Settings surface.

## Tokens and typography

`desktop/src/styles/tokens.css` owns the semantic values. Earlier `--color-*`
names remain aliases for page styles. Do not create a second palette in a page.
`styles.css` maps the semantic roles into Tailwind utilities. Document defaults
use the base layer, shared and feature layouts use the components layer, and
primitive utilities provide the final control states.

| Role | Value or rule |
| --- | --- |
| Canvas / main text | `#000000` / `#f5f5f5` |
| Card / popover | `97% #0a0a0a + 3% white` |
| Muted text / placeholder | `#a3a3a3` |
| Primary / primary text | `oklch(0.571 0.21 264)` / white |
| Focus / error | Primary blue / `#f87171` |
| Border / input border | White at 8% / 11% |
| Settings sidebar / hover / selection | Card tone / white at 4% / white at 3% |
| Typography | Local Inter Variable; 14 px body and controls, 12 px help, 11 px metadata |
| Geometry | 32 px desktop controls; 8 px control radius; 12 px groups; 16 px dialogs |
| Window | 240 px sidebar; 56 px icon rail below 768 px; 48 px header |
| Content | 896 px maximum including 20/24 px side padding; 24 px top; 48 px bottom |
| Forms | 16 px/600 section titles; 14 px/500 row labels; 12 px descriptions |
| Row descriptions | 18 px line height; balanced wrapping; 672 px maximum |
| Navigation | 8 px outer inset and icon gap; 10 px row inset; 32 px rows |
| Menus | 28 px minimum row height from 640 px; 32 px below; 16/18 px icons |
| Scrollbars | 6 px; foreground at 8%, 12% on hover; 3 px radius |
| Advanced disclosure | 40 px minimum trigger; 12 px/500 muted label; 14 px chevron; 6 px gap; 12/16 px side padding |
| Spacing | 4, 8, 12, 16, 20, 24 and 32 px |
| Motion | Existing T3 control and overlay transitions; reduced-motion override; immediate page navigation |

The root font size is 16 px so rem-based control geometry remains predictable.
The body is 14 px. Inter Variable is bundled with its Unicode subsets. Apple
platforms use their system font first. No remote font is loaded.
Use monospace for captured keybindings, versions and technical metadata. Error and warning
states need text as well as color. Lucide supplies shared icons.

Use semantic roles for surfaces, text, borders and states. Keep the black canvas
and neutral groups. `--muted` and `--accent` provide the shared selection and hover
tones. Use `--primary` for the main action in its context and `--ring` for focus.
Use `--destructive` for destructive actions and errors, and `--success` for
success feedback. Do not replace these roles with page-specific color values.
Provider brand colors remain within their brand controls.

## Reusable controls

`components/primitives/` contains the reusable Base UI components. Their
composition, Tailwind variants, `data-slot` names and state attributes form the
common control layer. Keep Base UI imports there rather than rebuilding keyboard,
focus, disabled or popup behavior in feature pages. `lib/utils.ts` merges
conditional utilities and resolves conflicting Tailwind classes.

Pages use the feature-facing facade in `components/ui.tsx`:

- `Button`: outline, primary, ghost and inline actions, default button type,
  loading state and disabled handling.
- `Input` and `TextArea`: styled shells around native editable controls. Preserve
  native events, input type, refs, form submission and accessible descriptions.
- `Row` and `Field`: associated labels and help text, with aligned controls.
- `Switch` and `Toggle`: labeled binary state, using the shared switch primitive.
- `Section`: a quiet heading outside a grouped panel with internal dividers.
- `SettingsDisclosure`: T3's `AdvancedSettings` pattern for advanced rows inside
  a section. Use its full-width trigger, Lucide chevron and shared Base UI
  collapsible panel instead of the browser's native disclosure marker. The
  chevron rotates in 150 ms; panel height changes in 200 ms. Reduced motion
  removes both transitions. Keep the panel mounted while closed to preserve
  existing input and operation lifetimes. Enter and Space toggle the control.
- `Confirm`: controlled modal dialog with title, description and explicit actions.
- `Picker`: searchable combobox with stable option IDs, keyboard selection,
  selected state, refresh, empty state and focus return.

`components/settings-navigation.tsx` renders grouped page buttons from the shared
button styles. Navigation remains available while a preference, refresh, or
text save is pending. The sidebar starts with Dictation and uses direct task
navigation without a global search or search shortcuts. Style and Text actions
remain visible for managed accounts. Dropdowns and libraries keep their local filters.
Dialogs and dropdowns retain their own keyboard handling.

`components/titlebar.tsx` owns the native drag region, identity, page context and
existing minimize, maximize and close commands. Page geometry belongs in
`styles/pages.css` and `styles/snippets.css`; window geometry belongs in
`styles/layout.css`. Reuse the facade instead of copying control styles.

## Settings organization

Keep T3's shared visual controls and separate work tasks from application
preferences. The workspace has six destinations. A footer Settings button opens
a controlled dialog and preserves the main page behind it. Do not duplicate
settings as main sidebar destinations. Rewrite and Translation are initial saved
text actions. Custom actions use the same editor and execution contract.

| Destination | Contents and order |
| --- | --- |
| Dictation | Microphone, recording mode and limits, transcription route and practice entry |
| Style | Cleanup level, optional action after dictation, application styles, then advanced review routing and instructions |
| Text actions | Named actions, state, shortcut, edit, duplicate and delete |
| Dictionary / Snippets / History | Separate content destinations with their existing filters and account guards |
| Settings: General | Output language, startup, updates and practice entry |
| Settings: Models and services | Cloud connections, local model setup and activation, then personal text processing profiles |
| Settings: Shortcuts | Application bindings and access to saved text-action shortcuts |
| Settings: Privacy | Local history storage and retention, or account history access |
| Settings: Account | Sign-in, session, allowance and account actions |

When local dictation is selected, put local-model setup first instead of the
cloud connection. This also keeps local onboarding on its chosen setup path.
Keep installation and activation visible beside local-model status. Put
streaming, optimization and removal in advanced options. Keep recording mode
with microphone and recording limits. Cleanup level belongs to Style. A disabled
cleanup route links to the matching cloud or local context in Style without changing a setting
automatically.

Use dialogs for one bounded edit: action definition, processing profile or app
style. Use shared dialog headers, footers, overflow, focus return and dismissal
rules. The Settings dialog uses a 184 px inner navigation column; below 768 px,
it uses a 56 px icon column with accessible labels. Content scrolls independently
from navigation and action footers. Keep dialog bounds inside the window at
640, 820 and 1040 px widths.

Action name, instructions, profile and shortcut remain local drafts until Save.
Cancel discards the dialog draft. Closing with unsaved edits asks whether to keep
editing or discard. A shortcut input receives focus only after the backend has
suspended native shortcuts. Restore failure keeps capture available for retry.
Duplicate starts a new draft with a new ID and no shortcut. Preview uses a saved
action and explicit sample text, and never publishes through the clipboard.
Translation requires its own target language.

Keep action refresh available in the loaded catalog and the editor. Refresh
preserves the draft. If the saved definition changed, show its instructions and
let the user choose the saved version or retain the draft before saving again.
An incomplete write must show how to refresh and recover.

Settings saves handle only Settings drafts. Main-page instructions and content
drafts keep their own owners. Profile edits use an explicit profile command;
they do not select another global workflow. Native window close accounts for
all open dirty editors. Account or endpoint changes reject stale writes and
results. Opening a dialog must not enable cloud processing or upload personal
actions to an account.

## New and changed pages

- Use the existing titlebar, sidebar, breadcrumb and bounded content container.
  Add navigation entries through their existing owner. Keep an
  accessible page heading and use `Section`, `Row` and `Field` for grouped forms.
- Keep section titles outside their panels, labels beside their controls where
  space permits, and help text with its field. Associate labels and descriptions
  with controls; give icon-only actions an accessible name. Preserve full text
  and localization placeholders when labels wrap.
- Use the typography, spacing scale and control variants above. Put layout rules
  in the existing layout owners. Do not add arbitrary colors, font sizes,
  radii, shadows, spacing or per-page control overrides. If a reusable pattern
  is missing, extend the shared owner and record its rule here.
- Use shared menu, picker, select, dialog and scroll-area primitives for overlays
  and lists. Keep their portal, viewport bounds, keyboard navigation, Escape
  handling and focus return. Separate destructive menu items from ordinary
  actions. Preserve the native titlebar drag and control regions.
- Keep automatic preferences, text drafts, pending state and account visibility
  under the UX contracts below. A visual change must preserve those behaviors.

## Action priority

Choose the primary action from the next useful step in the current screen and
state. Use at most one blue primary button in an action group. Secondary actions
use outline, ghost or inline variants according to the existing context. A
button's label or command name alone does not determine its color.

In `components/ui.tsx`, `Button` defaults to outline and `variant="primary"`
selects blue. The lower-level button primitive uses `variant="default"` for
blue; preserve this mapping when composing a menu trigger or another primitive.

| Context | Primary action | Secondary actions |
| --- | --- | --- |
| Initial sign-in method chooser | Blue Continue without an account | Provider and email choices retain their shared or brand styles |
| Email form | Blue Continue or Confirm code | Outlined guest access when available; inline Back |
| Account Settings sign-in chooser | No forced primary | Provider choices and outlined guest access |
| ChatGPT disconnected | Blue Connect with the ChatGPT mark | No connected-account usage action or menu |
| ChatGPT connected and authorized | Blue Manage usage | Outlined account-options menu |
| ChatGPT needs reconnection | Blue Reconnect with the ChatGPT mark | Outlined Manage usage and account-options menu |

Keep add-account, reconnect and model-refresh options in the connected-account
menu, with sign-out after a separator. Busy state keeps the existing Cancel
action and command gates. Contextual Save/Discard actions retain their position
and draft behavior; do not promote unrelated actions by matching their names.

## Desktop UX contracts

Python remains the only owner of configuration, accounts, secrets, audio,
history and workflow effects. UI components do not add a bridge command, data
migration or external service.

Page switches, selection lists and application shortcuts save automatically
through a targeted preference command. Action and profile dialogs keep their
controls in the dialog draft until Save. An automatic save must not commit unrelated text drafts.
Hosted Save and Delete remain pending until the complete backend job finishes.
The editor must not confirm or close on job acceptance. Keep failures visible
inside the affected dialog. Model profiles show the verified catalog and an
explicit refresh control. Do not require a user to type a ChatGPT model ID.
Existing library flags save only the selected flag under its account context.
New library entries remain drafts until explicitly saved.

Free text and numeric fields retain contextual Save/Discard actions in the page
flow. Navigation retains drafts by workflow and never stages them merely by
opening another page. Closing with pending text uses the unsaved-change
confirmation, including an explicit save-all action. Saving one page preserves
unsaved edits elsewhere and edits made after the save began.

Pending state belongs to the affected operation. The sidebar and unrelated
controls do not dim or become disabled for microphone tests, list refreshes,
saves or discards. A workflow page can show local loading while its route data
arrives. Async completions must not replace a later navigation or text edit.

The titlebar and sidebar stay fixed. The current page appears in the header
context; an accessible level-one heading remains in the page.
The content is centered and bounded. At 820 px, navigation remains labeled;
at 640 px, it becomes an icon rail with accessible names and hover titles.
The navigation uses
the shared scroll area with 12 px edge fades and hidden scrollbars; keyboard
focus removes the mask. The page keeps T3's 24 px fade below its header and a
stable scrollbar lane. Controls stack when needed. Library and history text can wrap and remain
available in full; layout must not truncate persisted content.

Authentication keeps full-width forms through each step. Managed accounts hide
personal providers. Destructive operations keep their confirmation and account
context checks. Opening a screen does not acquire the microphone or submit an
authentication request.

Initial setup and Account Settings share the same sign-in method selector:
Google, Microsoft, GitHub and email. The shared sign-in form keeps full-width
controls with a 44 px minimum height, 8 px gaps between method choices and a
14 px form gap during onboarding. Email opens its own form; Back retains the
typed address and returns focus to the email choice. A centered 12 px muted text
separator introduces access without an account in both the method chooser and
email form, with a 12 px gap before the guest button.
The initial sign-in screen places its controls directly below the welcome text
without a surrounding card, border, background or shadow. It uses a blue Continue
without an account button in the method chooser.
The email form and Account Settings use an outlined guest button. It opens local setup during onboarding and
returns to General from Account Settings. An expired managed session retains its
explicit sign-out action before personal processing becomes available.

Provider marks use local official assets. The Google button uses the current
gradient G and a bundled Google Sans Medium font, with its provider-specific
colors and spacing. Font and asset notices are in `desktop/licenses/`.
Reuse `components/provider-brand-icon.tsx`. Keep Google's font, colors and
spacing exception scoped to `styles/provider-brands.css`; other controls keep
the shared typography and semantic tokens. Do not fetch remote brand images
or fonts, redraw marks, or use text glyphs as provider logos.

The account and session owners remain django-allauth and the existing desktop
bridge. T3 uses Clerk's authentication service for its sign-in UI. Using the
[`SignIn` component](https://clerk.com/docs/react/reference/components/authentication/sign-in)
would require a Clerk authentication integration; local brand marks and shared
controls provide the requested presentation within Clarify's existing flow.

The ChatGPT account selector remains visible while connected. Reconnection
remains available after an uncertain refresh. All account, usage and model
actions use the existing ChatGPT session owner and command gates.

## Validation

For every new or changed page, compare the rendered result with the reference
screenshots and an existing page of the same type. Check 640, 820 and 1040 px
widths, long localized labels, wrapping and scroll boundaries. Verify hover,
focus, selected, disabled, loading, empty and error states where applicable.
For account UI, also inspect guest, email, managed-session, connected and
reconnect states affected by the change. Check keyboard entry, menu dismissal
and focus return. Retain screenshots of the affected states and identify which
are fixture evidence and which are native Windows evidence.

The screenshots below use the isolated controller fixture, with no user profile
or live audio. They show task navigation, the Settings dialog and the saved-action editor.

![Style and task navigation](images/settings-desktop-style.png)
![Settings dialog and privacy](images/settings-desktop-dialog.png)
![Text action editor](images/settings-desktop-action-editor.png)

Use `desktop/tests/settings.spec.ts` with `tests/web_settings_fixture.py` for
isolated controller-backed browser checks. Cover labels, help, keyboard, focus,
page navigation, local filters, automatic preferences, drafts, managed accounts
and 640/820/1040 px geometry. Run the TypeScript/production build and Settings
suite. Python behavior changes also require the Python suite. Native Windows checks cover the
Tauri/QProcess boundary and the actual window.

Automated checks establish only the tested interactions. Manual Windows
acceptance of DPI, global hotkeys, tray, transparency and passive pill focus
remains a separate gate. See [desktop responsiveness](desktop-performance.md)
for state ownership, measurements and their limits.
