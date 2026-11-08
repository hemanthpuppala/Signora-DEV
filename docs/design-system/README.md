# Signora design system

**Source of truth for UI and UX:** [`prototype.html`](prototype.html), a clickable prototype of all 28 screens. Open it in a browser and use **All screens** (bottom right) to navigate. The Next.js app in `apps/web` must port these tokens, components and flows; when the app and the prototype disagree, the prototype wins unless this file records a deliberate deviation.

## Principles
- **Pure black and white.** Dark only (`color-scheme: dark`). The only color in the product is the status dot.
- **Quiet typography.** Cormorant Garamond Light for headings and numbers; system sans at weight 300 for text; tracked uppercase micro-labels for structure.
- **Square and hairline.** No border radius. Separators are 1px white at 8% opacity. Buttons are ghost buttons (transparent, white text, hairline border).
- **Documents are paper.** PDFs render on an off-white "paper" surface (`--paper #f6f5f2`); roles are told apart by grayscale border weight and style, not hue.
- **One decision per screen.** Primary action is a single ghost button with a trailing arrow (`Create workspace →`); secondary actions are text links.

## Tokens
| Group | Tokens |
|---|---|
| Surfaces | `--bg #000`, `--surface #0a0a0a`, `--surface-2 #141414`, `--surface-3 #1f1f1f`, `--paper #f6f5f2`, `--paper-ink #1a1a1a` |
| Text | `--ink #fff`, `--t75`, `--t60`, `--t55`, `--t30` (white at that % opacity) |
| Lines | `--sep` (8%), `--r40`, `--r25`, `--r15`, `--r08`, `--r05` (white at that % opacity) |
| Roles on paper | `--role1 #8c8c8c`, `--role2 #5a5a5a`, `--role3 #b0b0b0`, `--firm #222` (+ matching `*f` fills) |
| Fonts | `--serif` Cormorant Garamond 300/400/500 (+ italic), `--sans` system UI, `--mono` Source Code Pro, `--logo` Inter Tight 500 |
| Radius | `0` everywhere |

## Status colors (dot only, label stays white)
`draft/pending #8e8e93` · `sent #64a8ff` · `opened #a594ff` · `viewed #ffb547` · `signed #4cd97b` · `completed #2fd5a8` · `declined #ff6b6b` · `expired #a1a1a6` (dashed ring) · `cancelled #a1a1a6` (solid ring).

## Type scale
`.display` 44–72px serif · `.h1` 36–56px · `.h2` 30–44px · `.sub` italic serif 20–28px · `.body` 16/26 · `.small` 13/20 · `.eyebrow` 10px, 0.45em tracking, uppercase · `.cap` 11px, 0.3em · `.metric` 44px serif.

## Components
Ghost button (`.btn`, `.btn-o` quiet, `.btn-x` destructive-quiet, disabled state) · text link button (`.link`) · underline-only fields (`.field`) · custom dropdown (`.dd`) and date/range picker (`.dp`) over hidden native controls · square checkbox, round radio · tabs with hairline underline · filter bar with panel and removable chips · metric tiles · project cards with 3-stat footer · grouped label/field blocks (`.blocks > .block`) · hairline tables inside a panel · status pill (`.st.<state>`) · notice / warning notice · timeline · drop zone · toast · sticky blurred top bar.

## Screens (prototype numbering)
Public: 01 Landing · 02 Sign up · 03 Log in · 04 Accept invite.
Console: 05 Projects home · 06 New project · 07 Project envelopes (search, filters, sort) · 08 Project read-only · 09 Project settings · 10 Documents · 11 Upload · 12 Detecting (progress timeline) · 13 Review fields (paper + side panel).
Sending: 14 New envelope (generated form, extra signers) · 15 Bulk send · 16 Envelope detail (recipients, email failure retry, timeline) · 17 Countersign · 18 Completed (certificate) · 19 Members · 20 Audit log.
Signer: 21 Request email · 22 Email code · 23 Consent · 24 Read and sign · 25 Confirmation · 26 Decline · 27 Link closed · 28 Phone signer (bottom-sheet signature pad).

## Writing and interaction principles (owner decisions, 2026-11-07)

Every screen and email follows these; they come from reviewing Phase 2 with the owner.

1. **Say only what the person needs here.** No text that repeats what the page already shows (the workspace
   name is in the top bar; do not repeat it in a heading), no taglines inside the console, nothing technical
   (versions, builds, health) in front of users.
2. **Explain where a decision is made, not on pages people revisit.** A role's description belongs in the
   invitation and on the accept page; Settings and People show only the role name.
3. **Plain words, named for the job.** Owner, Editor, Viewer; "Invite as", not "Workspace access"; messages say
   what to do next ("Ask the workspace owner if you need it back").
4. **State rules up front, as rules.** A hint under a field is the requirement in the industry's wording
   ("Use 12 or more characters."), not advice. Validate when the person leaves the field, never while they type;
   the server stays the authority and its messages use the same words.
5. **Hide what a person cannot do.** Areas (People) and actions ("New department") a person's role does not allow
   are not shown at all; no disabled buttons with reasons (owner decision, 2026-11-07, replacing "show it disabled
   with the reason"). The server still refuses the action if called directly.
6. **Keep the geometry calm.** Fields in a row line up by their labels (`FieldGrid`), buttons sit on the input line
   (`FieldAction`), each table action has its own column (`ActionCell`), navigation items share one baseline,
   and browser autofill keeps the black fields.

## Porting rules
- Tokens live once in `apps/web/src/shared/ui/tokens.css`; components in `apps/web/src/shared/ui/*` import them (SSoT). Feature code never hard-codes colors or fonts.
- Fonts load with `next/font/google` (self-hosted at build time) instead of the Google Fonts stylesheet link.
- Accessibility kept from the prototype: visible focus ring, labelled controls, keyboard dropdowns, `prefers-reduced-motion`.
- Prototype-only scaffolding is not ported: the "All screens" index, `Prototype:` toasts, sample data.

## Deliberate deviations
| Screen | Deviation | Reason | Recorded |
|---|---|---|---|
| 02 Sign up | Asks only for the email. Firm name, your name and password move to a new "verify" page opened from the emailed link. | Sign-up must not reveal whether an email is registered, so the account is created only after the email is verified ([Phase 2 LLD](../design/features/02-accounts.md), topic 1). | 2026-11-07 |
| 04 Accept invite | Shows the role name chosen by the inviter instead of workspace plus per-project access. | Roles are data per workspace (Phase 2 LLD, ADR-A1); per-project grants arrive in Phase 3. | 2026-11-07 |
| 04, 19 Role wording | Roles read **Owner / Editor / Viewer** with a one-line description (invite page, invite form, People, Settings) instead of Read and Read/write. | People-facing wording (Phase 2 LLD §8.1a). | 2026-11-07 |
| 19 Members | Named **People** in navigation; visible only with the `members.manage` permission (by default the creator). No saved-signature block yet (Phase 9). | Owner decision 2026-11-07 (Phase 2 LLD, topic 8). | 2026-11-07 |
