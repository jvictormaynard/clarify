# Desktop design system

The React/Electron desktop window follows the Wispr Flow Windows reference
with Clarify branding and semantic colors. Shared React controls retain their
existing focus, keyboard, bridge and lifecycle owners. Its workspace includes dictation, style, text actions, dictionary,
snippets and history. Application preferences and account access use a Settings
dialog. The fixed dock,
quick menus and Qt/QML recovery views retain their own theme and
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

The visual reference is the official Wispr Flow Windows v1.6.1400 package,
dated 5 November 2026. Its public [update metadata](https://dl.wisprflow.com/wispr-flow/win32/latest.json)
identifies SHA-256 `5c72e904d45a5974dca0c48234a5f290a8201e858b5f8afed2716d17c29466b3`.
Static package styles establish the dimensions below. Application source and
extracted assets are not shipped with Clarify.

Use the Home variant described in the [4 November navigation guide](https://docs.wisprflow.ai/articles/5096240724-navigating-the-wispr-flow-app-desktop-ios-and-android).
The same package also contains an older Dictation variant. Account entitlements
and runtime flags affect which features appear. Do not add unsupported meetings,
insights, notes or team controls. Clarify text actions use an additional catalog
entry. Native Windows captures are required before claiming pixel equivalence.

Base UI controls and the original T3-derived implementation retain their source
notices. Inter uses the existing bundled variable font under the SIL Open Font
License. Exact provenance is in
`desktop/licenses/source-components.json`. No remote font is loaded.

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
| Typography | Inter; body 14/20, metadata 12/20; Settings titles 28/28 |
| Geometry | 36 px inputs and normal buttons; 8 px controls; 12 px groups and dialogs |
| Window | 216 px sidebar, 256 px maximized, 60 px collapsed; 44 px header |
| Content | Main pane padding 40 px; max content width max(800 px, 50vw); outer radii 24/24/16/16 px |
| Forms | 16 px/600 section titles; 14 px/500 row labels; 12 px descriptions |
| Row descriptions | 18 px line height; balanced wrapping; 672 px maximum |
| Navigation | 12 px outer inset; 8 px row padding/gap; 18 px icons; 14/20 type at weight 550 |
| Menus | 28 px minimum row height from 640 px; 32 px below; 16/18 px icons |
| Scrollbars | 6 px; foreground at 8%, 12% on hover; 3 px radius |
| Advanced disclosure | 40 px minimum trigger; 12 px/500 muted label; 14 px chevron; 6 px gap; 12/16 px side padding |
| Spacing | 4, 8, 12, 16, 20, 24 and 32 px |
| Motion | Buttons 400 ms spring; switches 100/150 ms; dialogs 150 ms spring; menus 80 ms ease-out; immediate page navigation |

The root font size is 16 px so rem-based control geometry remains predictable.
The body uses Inter 14/20. Main headings and Settings titles use
Inter 28/28 at weight 400 with -0.04em tracking.
Use monospace for captured keybindings, versions and technical metadata. Error and warning
states need text as well as color. Lucide supplies shared icons.

Use semantic roles for surfaces, text, borders and states. Keep the black canvas
and neutral groups. `--muted` and `--accent` provide the shared selection and hover
tones. Use `--primary` for the main action in its context and `--ring` for focus.
Use `--destructive` for destructive actions and errors, and `--success` for
success feedback. Do not replace these roles with page-specific color values.
Provider brand colors remain within their brand controls.

Inter is an explicit Clarify exception to the reference typography. Preserve the
current layout, sizes and spacing when changing the font.

Shared flat buttons transition their background over 400 ms with
`--interaction-spring-ease`; they do not shrink on press. Switch tracks change
over 100 ms and thumbs travel over 150 ms with that spring curve, using the
current track geometry. Dialogs fade and scale from 0.9 over 150 ms with the same
curve. Their backdrops fade over 150 ms. Menus and searchable pickers fade over
80 ms ease-out. These values come from the pinned package's shared controls.
Keep Base UI's lifecycle attributes on the animated popup so close transitions
finish before it unmounts. Reduced motion removes these transitions. Keep the
existing Clarify surface colors, glass effects, focus rings and draft guards.
Static reference inspection does not prove every runtime or native interaction.

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
  Use `grouped={false}` for standalone multiline editors and their help or actions.
  These fields align with the heading without an outer card. Keep the textarea's
  own input border and focus state. `TextArea` also supports `unstyled` when a
  surrounding composer owns the field border and focus state.
- `SettingsDisclosure`: the shared collapsible pattern for advanced rows inside
  a section, library entry, help text or history comparison. Use its full-width
  trigger, Lucide chevron and shared Base UI
  collapsible panel instead of the browser's native disclosure marker. The
  chevron rotates in 150 ms; panel height changes in 200 ms. Reduced motion
  removes both transitions. Keep the panel mounted while closed to preserve
  existing input and operation lifetimes. History comparisons mount on expansion
  and unmount after collapse, so closed entries do not fetch text. Enter and Space
  toggle the control. Do not use native `details` or separate disclosure buttons.
- `Confirm`: controlled modal dialog with title, description and explicit actions.
- `Picker`: searchable combobox with stable option IDs, keyboard selection,
  selected state, refresh, empty state and focus return.

`components/settings-navigation.tsx` renders grouped page buttons from the shared
button styles. Navigation remains available while a preference, refresh, or
text save is pending. The sidebar starts with Home and uses direct task
navigation without a global search or search shortcuts. Actions and libraries remain visible for managed accounts. Dropdowns and libraries keep their local filters.
Dialogs and dropdowns retain their own keyboard handling.

`components/titlebar.tsx` owns the native drag region, identity, page context and
existing minimize, maximize and close commands. Page geometry belongs in
`styles/pages.css` and `styles/snippets.css`; window geometry belongs in
`styles/layout.css`. Reuse the facade instead of copying control styles.

## Settings organization

Home, Dictionary, Snippets, Style and Actions are direct sidebar entries.
Home retains the `history` PageId and the existing history owner. The logo sits above the sidebar entries. Settings stays below the main entries;
Account also opens from the top bar. The sidebar can collapse to a 60 px rail.

Home shows date-grouped history without shortcut, practice, microphone setup or
synchronization controls above it. All workspace search controls use the shared PageSearch component. History
queries are debounced and keep cursor pagination; closing search clears its filter.
History search shares the first visible date
heading row. Clear history lives in Settings → Data & Privacy and retains its
confirmation and account context. Each local calendar day has its own bordered list, with its date heading
above it and space between days. Date labels reuse the mobile formatter: localized
Today, then short month/day dates, with the year for older years. Use natural
capitalization, 18 px type with a 26 px line height, and refresh Today at local midnight. Pagination extends the existing day list
instead of starting another one. Time and device occupy the left metadata column. The device is always visible
below the time. The transcript and expanded comparison share the same left edge.
Original text is muted; Result keeps the foreground color. Correction follows the
comparison as a secondary action. Copy and delete appear
on hover or keyboard focus and remain visible for coarse pointers. Both icons
share one toolbar and equal hit areas. Copy feedback changes the icon to a
checkmark for 1.8 seconds without adding visible text. Opening a
transcript uses the shared 200 ms accordion transition to reveal bounded Original
and Result previews and correction controls. Read more opens a scrollable full-text
view, which loads further text as the user scrolls. Do not add chunk-navigation
buttons, a copy-original action or a divider above these details. The main page
scrollbar sits next to the panel border; padding belongs inside the scroll area.
Never derive total usage
or WPM from a bounded history page.

Settings opens a 960 by 640 px controlled dialog. Its Settings label sits inside
the sidebar; there is no full-width title bar. Keep the accessible dialog title
visually hidden and the X at the top right. It preserves the main page
behind it. Its navigation has a 192 px inner width plus 8 px padding per side;
compact windows retain the existing icon rail. Content has 48 px padding and
scrolls separately from navigation. The footer appears only for unsaved Settings
edits or an unresolved close request. With no pending edits, use the existing X
or Escape to close; do not reserve a bottom bar for a Done button. General contains
shortcuts, microphone/dictation configuration and output language. System owns
startup and updates. Account and Data & Privacy retain their existing owners.
Models and services and paired Devices remain as Clarify-specific sections.
Legacy shortcut links open General, retaining their original behavior.

Libraries share a title row with Info and a right-aligned Add button. Search and
an icon-only refresh button sit together below the introduction card. Refresh
reloads stored rows and synchronizes account library changes without saving or
discarding library drafts. Actions uses
the existing catalog refresh. Libraries use compact lists and separate Add/Edit
dialogs. Search starts as an
icon, opens and focuses its field on click, and closes on an outside click or
Escape. Closing clears the filter; outside dismissal preserves the clicked
action, and Escape returns focus to the search icon. Keep one shared vertical
gap between the list and its help disclosure. Dictionary dialogs
use a 480 px inner content width; Snippets uses 640 px. Padding and borders
produce outer widths of 530 and 690 px. Keep them bounded
inside compact windows. Validation keeps the editor open. Cancel has no write;
confirmation uses the existing context and draft owners. A dirty library editor
blocks native close until Apply or Cancel; Apply moves its text to the page draft,
where the existing Save/Discard and native-close commands own persistence. Additional recognition
and matching options remain available as Clarify features.

Actions use the saved-action catalog. Clicking an action opens its input,
output language, run, result and explicit Copy controls. Editing remains in a
separate dialog. Keep errors, cancellation and recovery visible when required.
All dialogs retain keyboard dismissal, focus return and dirty-state handling.

Style shows Text editing with Improve
clarity and Keep my words. Show Tone only when editing is allowed, with Keep my
tone, Formal and Casual. Keep my tone is an explicit natural style, distinct
from a legacy unset override. More options contains output language, the optional
automatic text action and advanced review settings.
Keep active legacy cleanup levels and tones readable until the user changes
them. Changing tone must not clear an automatic action. A disabled cleanup route
links to the matching cloud or local context without enabling it automatically.

Action name, instructions, profile and shortcut remain local drafts until Save.
Cancel discards the dialog draft. Closing with unsaved edits asks whether to keep
editing or discard. A shortcut input receives focus only after the backend has
suspended native shortcuts. Restore failure keeps capture available for retry.
Duplicate starts a new draft with a new ID and no shortcut. Use action and editor preview share the saved-action execution owner with explicit input, output language, revision and account context. Use action focuses the input and shows a selectable result with a Copy result button. Copy uses the current native result and validates its account context and operation generation. Running an action does not copy automatically. Configuration stays in the separate editor.
Translation requires its own target language.

General tone applies across applications. Very casual, Informal and Organized
remain readable for older general preferences until the user changes them.
Tone changes save automatically and apply to the next operation. They do not
enable a disabled refinement route. There is no application-specific setup.

Keep action refresh available in the loaded catalog and the editor. Refresh
preserves the draft. If the saved definition changed, show its instructions and
let the user choose the saved version or retain the draft before saving again.
An incomplete write must show how to refresh and recover.

Settings saves handle only Settings drafts, including transcription instructions
and recording limits. Style and library drafts remain outside that save. Main-page instructions and content
drafts keep their own owners. Profile edits use an explicit profile command;
they do not select another global workflow. Native window close accounts for
all open dirty editors. Account or endpoint changes reject stale writes and
results. Opening a dialog must not enable cloud processing or upload personal
actions to an account.

## Page titles and feature guides

Main pages and Settings use Inter at 28 px, regular weight, 28 px line height
and -0.04em tracking. The shared workspace header owns this title style.
Settings → About contains the Clarify name and the reported application version;
the main sidebar has no product/version footer.

Dictionary, Snippets and Actions have horizontal animated introduction cards
below the page title. Each shares the full guide's three scenes, cycling every
six seconds. All three save dismissal separately for the desktop profile and
keep the full guide under the info button. Focus inside a card pauses its cycle;
hidden documents and reduced motion also stop automatic cycling. Step buttons
keep all scenes available without automatic motion. The cards and mobile install promotion use the same plain ghost close button,
icon size and inset as the modal. The card replaces the old
introductory subtitles. Its decorative examples never modify real data.

Dictionary, Snippets and Actions have an info button beside the page title.
Hover or keyboard focus shows “How it works” with a short fade and scale
transition. The button opens a shared three-step visual guide. The guides use distinct nature scenes: green forest for Dictionary, warm dunes
for Snippets and a cool rocky coast for Actions. Each card and its full guide
share a scene and a dark overlay for clear text. Illustrated cards have no border,
so photo colors cannot bleed through a translucent outline. Devices keeps the blue mountain
lake. Examples keep the mobile CTA's restrained motion.
Side arrows and Left/Right keys change steps; Escape and Close dismiss the guide
and return focus to the info button. Reopening starts at the first step.
Reduced motion shows complete static examples. Examples never run providers,
change library data or access the clipboard. Short notes retain the relevant
rewriting and cloud-context limits. The existing library editors own all saves.

## New and changed pages

- Use the existing titlebar, sidebar and bounded content container.
  The shared page header shows a visible heading. Home uses date-grouped
  history rows. Compact layouts keep
  controls and text within the window.
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

The titlebar and sidebar stay fixed. The titlebar and the space around the
bounded content panel use the sidebar color. The content panel keeps its page
background. The current page appears in the header context; an accessible level-one heading remains in the page.
The content is centered and bounded. At 820 px, navigation remains labeled;
at 640 px, it becomes an icon rail with accessible names and hover titles.
The navigation uses
the shared scroll area with 12 px edge fades and hidden scrollbars; keyboard
focus removes the mask. Main content has no top fade, so headings retain full
contrast at the measured 40 px inset. It keeps a stable scrollbar lane. Controls stack when needed. Library and history text can wrap and remain
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
Authentication uses a centered 400 px column. Only the welcome screen shows
its logo and product description. The next screen groups microphone selection
and its explicit local test, shortcut keycaps with Change shortcut, and output
language in a 560 px column. Use three two-column form rows with quiet separators
and no surrounding card. Labels sit on the left, controls on the right; narrow
windows stack them. The compact Test action sits beside microphone selection.
Keep device warnings and test results visible. The test privacy note remains
available through its description and tooltip. Continue stops a microphone test before opening
the safe practice email. Before recording, the card shows the configured
shortcut prompt. Recording replaces that prompt with a short read-aloud
instruction and the italic, quoted passage below it.
Processing replaces the passage with its status. The completed transcript
fills the card body from the top left without an inner field border. The sample subject is visible
before recording and stays visible throughout practice. Both fields are read-only. The shortcut retains
the configured toggle or hold behavior. Practice has only Skip and Continue in
its footer. Continue stays disabled until a completed, nonempty transcript has
no error or blocked state. Skip also closes active recording safely. Error
recovery uses a contextual settings link. Starting again uses the shortcut.
Back appears on the left and the forward action on the right in onboarding
navigation rows, including email and code confirmation. Setup and practice
group Skip and Continue on the right, with Skip immediately before Continue. The sign-in
method choices retain their order. A completed transcript shows a success state;
Skip and failed attempts do not. Replay uses the same practice destination and
preserves completed onboarding. Local model setup remains available when a
model is missing.

Setup and practice scroll at short heights. Their titlebar keeps the drag
region and window controls. Step entry uses a 220 ms fade with 6 px movement;
success confetti ends after 1.4 seconds. Reduced motion removes both.
Workspace pages keep the existing titlebar identity and page context.

Home can show a compact, dismissible iPhone download card with a cropped, animated
keyboard preview over a blue landscape and an App Store QR. The card uses a
mobile-availability title, a short benefit statement and an outlined download
block with a 112 px QR code, scan instructions and iOS availability. On windows at least
1360 × 720 CSS px, it floats at the bottom-right with a reserved history gutter.
Smaller windows keep the card in the page. It stays until dismissed, with no
auto-close timer. Dismissal is local to this desktop profile and persists across
launches. A paired phone also suppresses the card; there is no cross-device
installation lookup.
Devices keeps the download QR and the same animated iPhone preview after
dismissal. The guide wraps into a vertical layout in narrow Settings panels.
Its download QR is separate from the computer-pairing QR. The demo uses a 390 × 852 pt iPhone screen canvas with a thin metal frame,
Dynamic Island, system status bar and light iOS surfaces scoped to the illustration.
Its keyboard follows the native Clarify extension: 58 pt toolbar, 220 pt keys,
and a recording panel that replaces the keys. The black output capsule shows
the language flag and Keep my tone, using the current tone label shared with
Settings and the native keyboard.
The 12-second edit zooms toward
the keyboard, shows recording and processing, then inserts the complete unsent
phrase and restores the keys. The animation loops automatically, including on
hover. Reduced motion shows the completed text without motion.

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

For every new or changed page, compare the rendered result with the pinned
reference and an existing page of the same type. Check 640, 820 and 1040 px
widths, long localized labels, wrapping and scroll boundaries. Verify hover,
focus, selected, disabled, loading, empty and error states where applicable.
For account UI, also inspect guest, email, managed-session, connected and
reconnect states affected by the change. Check keyboard entry, menu dismissal
and focus return. Retain screenshots of the affected states and identify which
are fixture evidence and which are native Windows evidence.

Keep fixture and native screenshots in CI artifacts. Do not commit review
captures as application assets or present an older capture as the current UI.

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

## Native dock

The Electron dock stays visible above the taskbar. Its idle handle expands on
hover and collapses after the pointer leaves. Menus share the hover delay so the
pointer can cross the gap. Presses retain the current presentation until release.
The dock cannot be dragged. Alt+R and the tray command expand or collapse its
controls; recording, processing, feedback and result panels remain available.

React owns this presentation state. Python owns workflow admission and results.
Electron owns the fixed monitor position, painted hit regions and passive focus.
Transparent surroundings remain click-through during transitions. The native
mouse activation handler retains real capture for buttons; it must not emulate
input or activate the dock. Qt/QML keeps its recovery presentation when the
Electron host fails.

Shortcut controls in Actions and General use one keycap button with a pencil
icon. The full control opens the existing editor or capture flow.

The compact dock is 36 px high with 28 px controls. Idle controls have 18 px
icons and 14 px regular-weight white tooltip text. Menus use 12 px text and
15 px icons. The dictation tooltip includes its current
configured shortcut. Output-language names start with a capital letter.
Processing uses a three-dot typing indicator. Successful workflow completion
shows a check and “Done” for 1.2 seconds, once per operation, then returns to the
handle. Errors, partial failures and cancellation retain their recovery controls.
This confirmation describes processing completion; it does not guarantee paste
acceptance by the target application.

The quick menu omits tone selection; the Style page retains that preference.
Cancellation Undo uses a 26 px button. Status text, Done and Undo use regular
12 px text. Loading and feedback widths follow their content with compact insets.

Microphone and Text Actions reveal adjacent menus on hover, click, or the right
arrow key. Chevrons mark these controls. Quit remains in the tray menu.

Recording bars are 2.5 px wide and occupy a centred 22 px track inside the 36 px
dock. Audio levels use a 28 ms attack and 65 ms release smoothing time constant.
Frame-rate height updates retain fully rounded ends at silence, without a
competing CSS transition.

The 12 recording bars use a 48 px track with 1.5 px gaps.
The target application icon is 22 px. Recording capsules shrink with the track.

The wave holds level changes below 0.015 to suppress input noise. Small settled
changes use 80 ms smoothing; larger changes retain the fast attack and release.
