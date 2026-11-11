import Link from "next/link";

import { cx } from "@/shared/lib/cx";
import { CONSOLE_HOME } from "@/shared/lib/routes";
import { SignatureLogo } from "@/shared/ui";

import { FIELD_NAMES, LANES, SECTIONS, TEAMS } from "./content";
import { LandingRuntime } from "./LandingRuntime";

import "./landing.css";

type LandingProps = {
  /** The visitor has a session: the calls to action open their workspace instead of signing up. */
  signedIn: boolean;
  /** Class that provides the page's sans font (`--font-landing-sans`). */
  className?: string;
};

function ResumeButton({ id }: { id: string }) {
  return (
    <button className="replay" type="button" id={id} hidden>
      <svg width="9" height="10" viewBox="0 0 9 10" aria-hidden="true">
        <path d="M0 0L9 5L0 10Z" fill="currentColor" />
      </svg>
      Resume demo
    </button>
  );
}

/** The hand-drawn arrow and label the extraction clip draws beside a found field. */
function FieldNote({ label }: { label: string }) {
  return (
    <div className="x-note is-fade">
      <svg width="96" height="38" viewBox="0 0 96 38" aria-hidden="true">
        <path
          className="x-shaft"
          pathLength={1}
          d="M94 8C80 2 66 5 60 15C55 24 61 34 69 30C77 26 73 12 61 14C49 16 36 25 8 25"
        />
        <path className="x-tip" pathLength={1} d="M17 18.5L8 25L17 31.5" />
      </svg>
      <b>{label}</b>
    </div>
  );
}

/**
 * The public landing page. This is the whole page as markup; `LandingRuntime` then animates it in
 * the browser. Layout, copy and motion follow docs/design-system/landing/prototype.html.
 */
export function Landing({ signedIn, className }: LandingProps) {
  const primary = signedIn
    ? { href: CONSOLE_HOME, label: "Open workspace" }
    : { href: "/signup", label: "Sign up" };
  const [clientName, matter, effectiveDate, clientSignature] = FIELD_NAMES;

  return (
    <div className={cx("signora-landing", className)}>
      <div className="page">
        <header className="top">
          <a className="top-brand" href="#top" aria-label="Signora, back to top">
            <SignatureLogo repeatSeconds={90} />
          </a>
          <nav className="top-links" aria-label="Sections" id="top-links">
            {SECTIONS.map((section) => (
              <a key={section.id} href={`#${section.id}`} data-sec={section.id}>
                {section.label}
              </a>
            ))}
            {signedIn ? null : (
              <Link className="push" href="/login">
                Sign in
              </Link>
            )}
            <span className="top-ind" id="top-ind" aria-hidden="true" />
          </nav>
          <button
            className="top-menu"
            type="button"
            id="menu-btn"
            aria-haspopup="dialog"
            aria-expanded="false"
            aria-controls="sheet"
          >
            Menu
          </button>
          <Link className="top-cta" href={primary.href}>
            {primary.label}
          </Link>
        </header>

        <main className="lp-main">
          {/* §01 Hero */}
          <section className="sec ink" id="top" aria-labelledby="hero-h">
            <div className="stage">
              <canvas
                id="hero-canvas"
                role="img"
                aria-label="Fine white ruled lines flow slowly down a black page. Moving the pointer bends them; clicking sends a swirl through them like a drop of ink."
              />
              <div className="stage-scrim" aria-hidden="true" />
              <div className="stage-copy">
                <h1 className="display hero-h rv-load rv-load--1" id="hero-h">
                  Send a template.
                  <br />
                  Get it back <i>signed.</i>
                </h1>
                <div className="stage-side">
                  <p className="lead soft rv-load rv-load--2">
                    E-signature for professional services firms. Upload a PDF or DOCX template, Signora finds the
                    fields, your team adds the client&apos;s details, and the client opens it with an access code to
                    sign in two steps.
                  </p>
                  <div className="btns rv-load rv-load--3">
                    <Link className="btn btn--solid" href={primary.href}>
                      {primary.label}
                    </Link>
                    <a className="btn btn--ghost" href="#how">
                      Try the flow{" "}
                      <span className="arr" aria-hidden="true">
                        ↓
                      </span>
                    </a>
                  </div>
                </div>
              </div>
            </div>
          </section>

          {/* §02 Templates */}
          <section className="sec lift" id="templates" aria-labelledby="tpl-h">
            <div className="strip">
              <span>§02 — Templates</span>
              <span className="strip-act">
                <span>Organised by team</span>
                <ResumeButton id="fd-resume" />
              </span>
            </div>
            <div className="split">
              <div className="fd-wrap">
                <div className="fd-stage">
                  <div className="fd" id="fd" role="group" aria-label={`${TEAMS[0].name} folder`}>
                    <span className="fd-back" />
                    <span className="fd-papers" id="fd-papers" />
                    <button className="fd-front" type="button" id="fd-front" aria-expanded="false">
                      <b id="fd-name">{TEAMS[0].name}</b>
                      <small>3 templates</small>
                    </button>
                  </div>
                  <div className="fd-teams" id="fd-teams" role="group" aria-label="Teams">
                    {TEAMS.map((team, i) => (
                      <button key={team.name} type="button" aria-pressed={i === 0}>
                        {team.name}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
              <div className="body-pad tpl-text" id="tpl-text">
                <h2 className="display kin tpl-h" id="tpl-h" aria-label="Every template, filed.">
                  <span className="tm">
                    <span>Every</span>
                  </span>
                  <span className="tm">
                    <span className="outline in-040">template,</span>
                  </span>
                  <span className="tm">
                    <span className="in-012">filed.</span>
                  </span>
                </h2>
                <p className="lead soft tpl-lead m-hide">
                  Keep your firm&apos;s templates in folders by practice area or team, so everyone starts from the
                  right, current version.
                </p>
              </div>
            </div>
          </section>

          {/* §03 Extraction */}
          <section className="sec ink" id="extract" aria-labelledby="extract-h">
            <div className="strip">
              <span>§03 — Extraction</span>
              <span>Every field, found</span>
            </div>
            <div className="split">
              <div className="waves">
                <div className="x-status glass" id="x-status-wrap" aria-hidden="true">
                  <span className="x-dot" />
                  <span id="x-status">Reading template</span>
                </div>
                <div
                  className="x-stage"
                  role="img"
                  aria-label="A template engagement letter is read. Each blank is found and labelled in turn: client name, matter, effective date and client signature."
                >
                  <article className="x-sheet" id="x-sheet" aria-hidden="true">
                    <div className="x-head">
                      <b>Engagement Letter</b>
                      <span>Template · DOCX</span>
                    </div>
                    <div className="x-rows">
                      <div className="x-row">
                        Client
                        <span className="xf" data-i="0" />
                      </div>
                      <div className="x-row">
                        Matter
                        <span className="xf" data-i="1" />
                      </div>
                      <div className="x-row">
                        Effective
                        <span className="xf xf--short" data-i="2" />
                      </div>
                    </div>
                    <p>
                      Thank you for asking us to act for you on the matter above. This letter sets out the scope of
                      our work, how we charge, and the terms on which we will act.
                    </p>
                    <div className="x-sig">
                      <div>
                        <span className="xf" data-i="3" />
                        Client
                      </div>
                      <div>
                        <span className="x-firm" />
                        For the firm
                      </div>
                    </div>
                    <span className="x-halo" aria-hidden="true" />
                    <span className="x-ring" aria-hidden="true" />
                    {FIELD_NAMES.map((name) => (
                      <FieldNote key={name} label={name} />
                    ))}
                  </article>
                </div>
              </div>
              <div className="body-pad">
                <h2 className="display kin" id="extract-h" aria-label="Every field, found.">
                  <span data-drift="-60">Every</span>
                  <span data-drift="70" className="outline in-050">
                    field,
                  </span>
                  <span data-drift="-40" className="in-018">
                    found.
                  </span>
                </h2>
                <p className="lead soft rv m-hide">
                  Signora reads your template and marks what needs filling: the people, the matter, the dates, and
                  where each person signs.
                </p>
              </div>
            </div>
            <div className="row fields-row m-hide" id="fields-row">
              {[clientName, matter, effectiveDate, clientSignature].map((name, i) => (
                <div key={name}>
                  <small>{`0${i + 1}`}</small>
                  <b>{name}</b>
                </div>
              ))}
            </div>
          </section>

          {/* §04 Try it */}
          <section className="sec lift" id="how" aria-labelledby="how-h">
            <div className="strip">
              <span>§04 — Try it</span>
              <span className="strip-act">
                <span>Build a real envelope, right here</span>
                <ResumeButton id="demo-resume" />
              </span>
            </div>
            <div className="split">
              <div className="body-pad m-hide">
                <h2 className="display kin how-words" id="how-h" aria-label="Upload, extract, fill, send.">
                  <span data-drift="-50" className="is-on">
                    Upload.
                  </span>
                  <span data-drift="60">Extract.</span>
                  <span data-drift="-36">Fill.</span>
                  <span data-drift="50">Send.</span>
                </h2>
                <p className="lead soft rv">
                  Four steps from template to envelope. Each one lights up as you go, and the code you get at the end
                  opens the document on the phone below.
                </p>
              </div>
              <div className="builder" id="builder">
                <span className="demo-cursor" id="demo-cursor" aria-hidden="true">
                  <svg width="34" height="36" viewBox="0 0 28 30">
                    <path
                      d="M4 3v20.5l5.3-4.9 3.7 8.4 4-1.8-3.7-8.3 7.4-.3z"
                      fill="#ffffff"
                      stroke="#0b0b0b"
                      strokeWidth="1.7"
                      strokeLinejoin="round"
                    />
                  </svg>
                </span>
                <ol className="steps" aria-label="Envelope steps">
                  <li aria-current="step">01 Upload</li>
                  <li>02 Extract</li>
                  <li>03 Details</li>
                  <li>04 Send</li>
                </ol>
                <div className="panes">
                  <div className="pane is-active" data-pane="1">
                    <h3 tabIndex={-1}>Upload your template</h3>
                    <label className="drop" id="drop" htmlFor="file-in">
                      <svg width="26" height="26" viewBox="0 0 24 24" aria-hidden="true">
                        <path
                          d="M12 16V4 M7 9l5-5 5 5 M4 15v5h16v-5"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="1.4"
                        />
                      </svg>
                      <b>Drop a PDF or DOCX</b>
                      <span>or click to choose a file</span>
                    </label>
                    <input
                      className="sr"
                      type="file"
                      id="file-in"
                      accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    />
                    <div id="file-slot" />
                    <p className="err" id="file-err" role="alert" />
                    <div className="pane-foot">
                      <button className="link-btn" type="button" id="use-sample">
                        Use a sample template
                      </button>
                      <button className="btn btn--solid" type="button" id="to-2" disabled>
                        Extract fields{" "}
                        <span className="arr" aria-hidden="true">
                          →
                        </span>
                      </button>
                    </div>
                  </div>
                  <div className="pane" data-pane="2">
                    <h3 tabIndex={-1}>Fields, extracted</h3>
                    <div className="scan" id="scan" aria-hidden="true">
                      <i />
                      <i />
                      <i />
                      <i />
                      <i />
                      <i />
                    </div>
                    <ul className="found" id="found" aria-live="polite" />
                    <div className="pane-foot">
                      <span className="note-sm" id="extract-note">
                        Reading the document…
                      </span>
                      <button className="btn btn--solid" type="button" id="to-3" disabled>
                        Enter details{" "}
                        <span className="arr" aria-hidden="true">
                          →
                        </span>
                      </button>
                    </div>
                  </div>
                  <div className="pane" data-pane="3">
                    <h3 tabIndex={-1}>Enter client details</h3>
                    <form className="form" id="details" noValidate>
                      <label className="field" htmlFor="c-name">
                        Client name
                        <input id="c-name" autoComplete="name" placeholder="Full name" required />
                        <span className="err" id="c-name-err" />
                      </label>
                      <label className="field" htmlFor="c-email">
                        Client email
                        <input
                          id="c-email"
                          type="email"
                          autoComplete="email"
                          placeholder="name@example.com"
                          required
                        />
                        <span className="err" id="c-email-err" />
                      </label>
                      <label className="field" htmlFor="c-matter">
                        Matter
                        <input id="c-matter" placeholder="Optional" />
                      </label>
                    </form>
                    <div className="pane-foot">
                      <button className="link-btn" type="button" data-back="2">
                        Back
                      </button>
                      <button className="btn btn--solid" type="submit" form="details" id="to-4">
                        Review{" "}
                        <span className="arr" aria-hidden="true">
                          →
                        </span>
                      </button>
                    </div>
                  </div>
                  <div className="pane" data-pane="4">
                    <div className="send-view" id="send-view">
                      <h3 tabIndex={-1}>Ready to send</h3>
                      <dl className="summary" id="summary" />
                      <div className="pane-foot">
                        <button className="link-btn" type="button" data-back="3">
                          Edit details
                        </button>
                        <button className="btn btn--solid" type="button" id="send-btn">
                          Send for signature
                        </button>
                      </div>
                    </div>
                    <div className="sent-view" id="sent-view" hidden>
                      <h3 tabIndex={-1}>Sent. Here is the access code.</h3>
                      <p className="soft" id="sent-line" />
                      <div className="code-show" id="code-show" />
                      <div className="pane-foot">
                        <button className="btn btn--ghost" type="button" id="copy-code">
                          Copy code
                        </button>
                        <a className="btn btn--solid" href="#sign" id="as-client">
                          Open as your client{" "}
                          <span className="arr" aria-hidden="true">
                            ↓
                          </span>
                        </a>
                      </div>
                      <button className="link-btn self-start" type="button" id="new-env">
                        Start a new envelope
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </section>

          {/* §05 Signing */}
          <section className="sec ink" id="sign" aria-labelledby="sign-h">
            <div className="strip">
              <span>§05 — Signing</span>
              <span className="strip-act">
                <span>What your client sees</span>
                <ResumeButton id="phone-resume" />
              </span>
            </div>
            <div className="split">
              <div className="body-pad on-dark sign-pad">
                <h2 className="display kin" id="sign-h" aria-label="Two steps to sign, at most.">
                  <span data-drift="-50">Two steps</span>
                  <span data-drift="60" className="outline in-045">
                    to sign,
                  </span>
                  <span data-drift="-36" className="in-012">
                    at most.
                  </span>
                </h2>
                <ol className="two m-hide">
                  <li className="rv">
                    <small>01</small>
                    <b>Open with the access code</b>
                    <span>The document stays closed until the code is entered.</span>
                  </li>
                  <li className="rv">
                    <small>02</small>
                    <b>Review and sign</b>
                    <span>Read it in full, then sign with a finger, stylus or mouse.</span>
                  </li>
                </ol>
              </div>
              <div className="phone-wrap">
                <div className="phone rv">
                  <div className="screen" id="screen">
                    <form className="view is-on" id="v-code" noValidate>
                      <div className="v-head">
                        <small>Step 1 of 2</small>
                        <b id="v-doc-1">Engagement Letter</b>
                      </div>
                      <div className="v-body">
                        <span className="v-title">Enter your access code</span>
                        <fieldset className="digits" id="digits">
                          <legend className="sr">Access code, six digits</legend>
                          {[1, 2, 3, 4, 5, 6].map((n) => (
                            <input
                              key={n}
                              id={`d${n}`}
                              inputMode="numeric"
                              autoComplete={n === 1 ? "one-time-code" : "off"}
                              maxLength={1}
                              aria-label={`Digit ${n}`}
                            />
                          ))}
                        </fieldset>
                        <p className="err" id="code-err" role="alert" />
                        <div className="lockline" id="lockline">
                          <svg width="28" height="28" viewBox="0 0 32 32" aria-hidden="true">
                            <rect
                              x="8"
                              y="14"
                              width="16"
                              height="12"
                              fill="none"
                              stroke="currentColor"
                              strokeWidth="1.5"
                            />
                            <path
                              className="shackle"
                              d="M11 14v-3.5a5 5 0 0 1 10 0V14"
                              fill="none"
                              stroke="currentColor"
                              strokeWidth="1.5"
                            />
                          </svg>
                          <span id="v-from">Sent by [Your firm]</span>
                        </div>
                      </div>
                      <div className="v-act">
                        <button className="btn btn--solid" type="submit" id="open-doc" disabled>
                          Open document
                        </button>
                      </div>
                    </form>
                    <div className="view" id="v-sign">
                      <div className="v-head">
                        <small>Step 2 of 2</small>
                        <b id="v-doc-2" tabIndex={-1}>
                          Engagement Letter
                        </b>
                      </div>
                      <div className="v-body">
                        <div className="v-lines" aria-hidden="true">
                          <i />
                          <i />
                          <i />
                          <i />
                          <i />
                          <i />
                          <i />
                        </div>
                        <div className="pad-block">
                          <div className="pad" id="pad">
                            <canvas
                              id="pad-canvas"
                              aria-label="Signature pad. Draw your signature with a finger, stylus or mouse."
                            />
                            <span className="pad-line" aria-hidden="true" />
                            <span className="pad-hint">Sign here</span>
                          </div>
                          <div className="pad-row">
                            <span id="v-signer">Client signature</span>
                            <button className="link-btn link-btn--xs" type="button" id="pad-clear">
                              Clear
                            </button>
                          </div>
                        </div>
                      </div>
                      <div className="v-act">
                        <button className="btn btn--solid" type="button" id="sign-btn" disabled>
                          Sign document
                        </button>
                      </div>
                    </div>
                    <div className="view v-done" id="v-done" role="status" aria-live="polite">
                      <svg className="done-ring" viewBox="0 0 64 64" aria-hidden="true">
                        <circle cx="32" cy="32" r="29" fill="none" stroke="currentColor" strokeWidth="1.4" />
                        <path d="M20 33l8 8 16-17" fill="none" stroke="currentColor" strokeWidth="1.6" />
                      </svg>
                      <b className="display done-h">Signed.</b>
                      <span className="note-sm" id="done-time">
                        Just now
                      </span>
                      <button className="btn btn--ghost btn--sm" type="button" id="sign-reset">
                        Start over
                      </button>
                    </div>
                  </div>
                </div>
                <span className="phone-hint m-hide" id="phone-hint">
                  Use the code from §04, or any six digits
                </span>
              </div>
            </div>
          </section>

          {/* §06 For your firm */}
          <section className="sec seal" id="firm" aria-labelledby="firm-h">
            <div className="strip">
              <span>§06 — For your firm</span>
              <span>Workspace · Audit trail · Access</span>
            </div>
            <div className="split">
              <div className="body-pad">
                <h2 className="display kin" id="firm-h" aria-label="Built for the whole firm.">
                  <span data-drift="-50">Built for</span>
                  <span data-drift="60" className="outline in-045">
                    the whole
                  </span>
                  <span data-drift="-36" className="in-015">
                    firm.
                  </span>
                </h2>
                <p className="lead soft rv m-hide">
                  One workspace for your team. Every envelope is recorded from upload to signature, and each person
                  sees only what their role allows.
                </p>
              </div>
              <div className="trail-wrap">
                <div
                  className="lanes"
                  id="trail"
                  role="img"
                  aria-label="A sample record for an engagement letter, shown as hand-offs between people. Associate: template uploaded. Signora: fields found. Associate: sent, locked with an access code. Client: opened with the code, then signed. Partner: filed."
                >
                  <div className="ln-cap" aria-hidden="true">
                    <span>Record · Engagement Letter</span>
                    <span>Sample</span>
                  </div>
                  <div className="ln-stage" id="ln-stage" aria-hidden="true">
                    <div className="ln-cols" id="ln-cols">
                      {LANES.map((lane) => (
                        <div key={lane}>{lane}</div>
                      ))}
                    </div>
                    <div className="ln-fade" id="ln-fade">
                      <svg className="ln-svg" id="ln-svg" />
                      <div id="ln-labels" />
                      <span className="ln-tok" id="ln-tok" />
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </section>

          <section className="sec feats-sec" aria-label="What firms get">
            <div className="row feats">
              <div>
                <small>01</small>
                <b>Team workspace</b>
                <span>Templates and envelopes shared across your firm, in one place.</span>
              </div>
              <div>
                <small>02</small>
                <b>Audit trail</b>
                <span>Every upload, send, open and signature recorded, with who and when.</span>
              </div>
              <div>
                <small>03</small>
                <b>Secured signing</b>
                <span>Documents stay closed until the client enters their access code.</span>
              </div>
              <div>
                <small>04</small>
                <b>Role-based access</b>
                <span>Partners, associates and staff each see what their role allows.</span>
              </div>
            </div>
          </section>

          {/* §07 Join */}
          <section className="sec ink" id="join" aria-labelledby="join-h">
            <div className="strip">
              <span>§07 — Join</span>
              <span>Get started</span>
            </div>
            <h2 className="display join-kin" id="join-h" aria-label="Send it. Signed.">
              <span data-drift="-140">Send it.</span>
              <span data-drift="140" className="outline join-in">
                Signed.
              </span>
            </h2>
            <div className="row">
              <div>
                <p className="lead soft">
                  {signedIn
                    ? "Your workspace is ready. Upload a template and send your next envelope."
                    : "Create your firm's workspace, upload a template, and send your first envelope."}
                </p>
              </div>
              <div className="row-center">
                <div className="btns">
                  <Link className="btn btn--solid btn--lg" href={primary.href}>
                    {primary.label}
                  </Link>
                  <a className="btn btn--ghost btn--tall" href="#how">
                    Try the flow
                  </a>
                </div>
              </div>
            </div>
            <div className="band">
              <canvas id="band-canvas" aria-hidden="true" />
            </div>
          </section>
        </main>

        <footer className="foot">
          <div>
            <span className="display foot-name">Signora</span>
            <span className="foot-note">E-signature for professional services firms</span>
          </div>
          <nav aria-label="Footer">
            <small className="foot-label">Explore</small>
            <div className="foot-links">
              {SECTIONS.map((section) => (
                <a key={section.id} href={`#${section.id}`}>
                  {section.label}
                </a>
              ))}
            </div>
          </nav>
          <div className="foot-base">
            <span>PDF · DOCX</span>
            <span>© 2026 Signora</span>
          </div>
        </footer>
      </div>

      <div className="sheet" id="sheet" role="dialog" aria-modal="true" aria-label="Menu" hidden>
        <div className="sheet-panel">
          {SECTIONS.map((section) => (
            <a key={section.id} href={`#${section.id}`} data-sheet-close>
              {section.label} <span aria-hidden="true">→</span>
            </a>
          ))}
          {signedIn ? null : (
            <Link href="/login" data-sheet-close>
              Sign in <span aria-hidden="true">→</span>
            </Link>
          )}
        </div>
      </div>

      <div className="toast" id="toast" role="status" aria-live="polite" />
      <LandingRuntime />
    </div>
  );
}
