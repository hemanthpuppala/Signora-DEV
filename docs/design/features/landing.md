# Landing page

The public page at `/`: what Signora is, shown with working demos, with a way in for firms.

## 1. Problem

A visitor who opens the site's address saw a log-in form and nothing about the product. The landing
page explains the product to a professional services firm in one scroll and leads to sign-up or,
for someone already signed in, to their workspace.

The approved design is `docs/design-system/landing/prototype.html` (one self-contained file). It is
the source of truth for layout, copy and motion; this document records how it is built into the app
and where the app deliberately differs.

## 2. Functional requirements

- **FR-1** `/` shows the landing page to everyone, signed in or not.
- **FR-2** Without a session, the call to action reads "Sign up" in the header, the hero and the
  closing section and goes to `/signup`; "Sign in", in the header, goes to `/login`. The footer does
  not repeat either.
- **FR-3** With a session, those calls to action read "Open workspace" and go to the console's home;
  "Sign in" is not shown.
- **FR-4** The console's home (the departments list) is `/departments`. Logging in, accepting an
  invitation and finishing sign-up land there; a signed-out visit to it goes to `/login`.
- **FR-5** The page has the prototype's sections in order: hero, Templates, Extraction, Try it,
  Signing, For your firm, the features row, Join, footer; the header links to each and underlines
  the one in view.
- **FR-6** Every self-playing demo (folder, extraction, envelope builder, phone, record) plays only
  while in view. A demo the visitor can operate (folder, builder, phone) stops on any interaction,
  shows "Resume demo", and plays again from the start on Resume or after 60 s without interaction.
- **FR-7** An envelope the visitor sends in the builder opens on the phone with its access code and
  no other; the demo's own envelope does not.
- **FR-8** With reduced motion requested, nothing plays by itself and each demo shows its finished
  state.
- **FR-9** Nothing the visitor enters in a demo leaves the browser.

## 3. Non-functional requirements

- **NFR-1 Security.** The page runs under the app's existing Content Security Policy unchanged: no
  style attributes in the markup, no inline or third-party scripts, fonts from our own origin.
- **NFR-2 Isolation.** The page's styles cannot affect the console, and the console's cannot break
  the page.
- **NFR-3 No leaks.** Leaving the page stops every timer, animation frame, listener and observer it
  started.
- **NFR-4 Reach.** The page reads in full as server-rendered HTML before any script runs. No
  horizontal scroll from 320 px up. Where WebGL is unavailable the hero shows still lines.
- **NFR-5 Cost while idle.** A demo out of view schedules no animation frames.

## 4. Rules

- The page states only real capabilities and invents no numbers, customers or prices. Sample data
  is labelled as a sample. Formats named are PDF and DOCX; signing is two steps at most.
- Dark only, like the console. Black and white, with oxblood used once (§06) and manila only on the
  folder.
- Whether a visitor is "signed in" is decided on the server by the session cookie being present,
  the same check the request proxy makes. A stale cookie shows "Open workspace"; the console then
  sends that visitor to log in.

## 5. Architecture decision

**Context.** The prototype is one HTML file: about 600 lines of CSS using global class names, and
about 900 lines of script that animate canvases, WebGL and timed sequences by toggling those
classes. The app's console is built from React components styled with CSS Modules and shared
tokens, under a nonce-based CSP.

**Decision.**

1. *Markup is a server component* (`features/landing/Landing.tsx`). The whole page is static HTML;
   the only input is whether the visitor has a session.
2. *Behaviour is a set of small controllers*, one per section, in `features/landing/runtime/`, each
   `mountX(root, scope, reduced)`. One client component (`LandingRuntime`) starts them after the
   page loads and stops them on leave. The demos are canvas drawing and timed sequences, which are
   imperative in any framework; keeping them outside React state keeps them frame-accurate to the
   prototype and keeps the page's React cost near zero.
3. *The shared rules live once.* `runtime/autoplay.ts` holds the play / take over / resume rule
   (FR-6) for all five demos. A `Scope` owns every listener, timer, frame and observer, so
   one `dispose()` satisfies NFR-3 (it lives in `shared/lib/scope.ts`, since the shared logo uses
   it too). Sample content used by both markup and demos is in `content.ts`.
4. *Styles are one stylesheet, `landing.css`, nested under the page's root class* rather than CSS
   Modules. The prototype's class names are the contract between its CSS and its script; keeping
   them makes the port checkable line by line against the prototype. Nesting everything under
   `.signora-landing`, and prefixing the keyframes and registered properties (which are global by
   nature) with `lp-`, gives the isolation CSS Modules would (NFR-2).
5. *The landing page has its own tokens*, defined on its root class. Its palette and type scale are
   a different system from the console's, so sharing `tokens.css` would couple two designs that
   change for different reasons.
6. *Route constants have one home*: `shared/lib/routes.ts` holds the console's home path and the
   session cookie's name, used by the proxy, the session code, the console shell and the landing
   page.

**Consequences.** The landing page is not built from the console's UI components and does not
follow the console's design system; `docs/design-system/README.md` records that. The section
controllers find their elements by id, so the markup's ids and the controllers must change together;
a missing element fails loudly at mount (`runtime/dom.ts`).

### Differences from the prototype

| Prototype | App | Why |
|---|---|---|
| "Request access" and "Sign in" open front-end-only dialogs | "Sign up" and "Sign in" link to `/signup` and `/login` (FR-2) | The product has self-serve sign-up and password log-in; a dialog that stores nothing would mislead, and nothing is requested |
| Closing section says firms are admitted one at a time | Says what signing up leads to: a workspace, a template, a first envelope | The page states only what the product does |
| Footer: name, a list of links, formats and copyright in three columns | Name and tagline, the section links as a labelled group, then one base line with formats and copyright | One idea per group; the ways in are not repeated under the closing section |
| The signing logo is part of the page's script | A shared component, `shared/ui/SignatureLogo`, also used by the console and sign-in top bar | One logo on every page |
| Follows the visitor's light or dark setting | Dark only | Matches the console |
| Style attributes on some elements | Classes at the end of `landing.css` | NFR-1 |
| Fonts from Google at run time | `next/font`, served from our origin | NFR-1 |
| Demo timers keep running | Stopped on leave | NFR-3; the app navigates without reloading |

## 6. Data

None. The page reads no API and stores nothing. The signature's pen path (`shared/ui/signature/penPaths.ts`) is
recorded data from the brand animation and is kept as data.

## 7. Algorithms and cost

- Autoplay: a state machine (`on`, `taken`, `visible`, a run counter). Every operation is O(1); a
  superseded pass notices on its next step by comparing its run number.
- Signature and logo: ink stamps are sorted by time, and a cursor advances through them, so each
  frame draws only the new stamps: O(stamps) over a whole pass, not per frame.
- Record path: one SVG path; the token's position is `getPointAtLength`, O(1) per frame.
- Hero: one full-screen triangle and a fragment shader; cost is per pixel, capped at a pixel ratio
  of 1.5, and it stops when out of view (NFR-5).

## 8. Interfaces

- `Landing({ signedIn, className })`: the page.
- `mountLanding(root): () => void`: starts every controller; the return value stops them.
- `SignatureLogo({ className })` (shared): the signing logo on a canvas. Its ink is the CSS `color`;
  the gaps in the quill take `--signature-paper`. It signs once per tab and then rests, so moving between pages
  does not replay it. With `repeatSeconds` it signs again after resting that long; only the landing
  page sets it (90 s).
- `createAutoplay({ scope, reduced, watch, play, resume?, onStart?, onStop? })` returns
  `{ isOn(), takeOver(), restart() }`. `play(alive)` is one pass; it resolves `false` when cut short.
- `mountPhoneSigning(...)` returns `{ setEnvelope(envelope | null), focusCode() }`, which the
  builder uses for FR-7.

## 9. Test strategy

| Requirement | Check |
|---|---|
| FR-2, FR-3, FR-5, NFR-1 (no style attributes) | `Landing.test.tsx` |
| FR-6, FR-8, NFR-3 | `runtime/autoplay.test.ts` (fake timers) |
| FR-4 | `session.test.tsx` (`safeNext`), existing console tests |
| NFR-1, NFR-4, FR-7, the demos themselves | Production build in a browser: no console or CSP errors, each demo reaches its end state, no horizontal scroll at 390 px and 1440 px |

The demos need canvas, WebGL and layout, which the unit-test DOM does not have; they are verified in
a browser against the production build, where the CSP is strict.

## Task Tracker

| # | Task | Status | Evidence of completion |
|---|------|--------|------------------------|
| 1 | Console home moves to `/departments`; route constants in one place | done | `shared/lib/routes.ts`; `session.test.tsx` |
| 2 | Page markup and scoped stylesheet | done | `Landing.tsx`, `landing.css`; `Landing.test.tsx` |
| 3 | Section controllers, autoplay and clean-up | done | `runtime/`; `runtime/autoplay.test.ts` |
| 4 | Lint, typecheck, unit tests, production build | done | 328 web tests pass; `next build` succeeds |
| 5 | Browser check of the production build (desktop, phone, reduced motion) | done | no console or CSP errors; demos reach their end states; 0 px horizontal overflow |
| 6 | Signing logo as a shared component, in every top bar | done | `shared/ui/SignatureLogo.tsx`; seen on `/` and `/login` in a browser |
| 7 | "Sign up" as the one call to action; footer regrouped | done | `Landing.test.tsx` |
| 8 | Frosted blur applies in Chromium (prefixed declaration first, so the build keeps both) | done | computed `backdrop-filter` on the header and status pill in a browser |
