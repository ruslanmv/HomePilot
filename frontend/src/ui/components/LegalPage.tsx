/**
 * LegalPage — HomePilot Terms of Service & Privacy Policy.
 *
 * Premium, enterprise-styled, self-contained legal pages served pre-auth at
 * `/terms` and `/privacy` (wired in main.tsx — the login footer links here).
 *
 * These documents are written for an Apache-2.0, self-hosted, local-first
 * open-source project: the person or organisation that runs a given HomePilot
 * instance is its operator/data-controller. The text is a good-faith template
 * following common OSS practice — it is NOT legal advice; operators should
 * adapt it (governing law, contact, jurisdiction) and seek counsel as needed.
 *
 * Design: dark premium theme consistent with AuthScreen, scoped under
 * `.hp-legal`, responsive, with a sticky table of contents on wide screens.
 */
import React from 'react'

export type LegalKind = 'terms' | 'privacy'

const LAST_UPDATED = 'July 4, 2026'
const REPO_URL = 'https://github.com/ruslanmv/HomePilot'
const LICENSE_URL = 'https://www.apache.org/licenses/LICENSE-2.0'

interface Section {
  id: string
  title: string
  body: React.ReactNode
}

function BrandMark() {
  return (
    <svg className="hp-legal-logo" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 120" fill="none" aria-label="HomePilot">
      <defs>
        <linearGradient id="lg-grad" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#06b6d4" />
          <stop offset="50%" stopColor="#3b82f6" />
          <stop offset="100%" stopColor="#8b5cf6" />
        </linearGradient>
        <filter id="lg-glow" x="-20%" y="-20%" width="140%" height="140%">
          <feDropShadow dx="0" dy="2" stdDeviation="6" floodColor="#3b82f6" floodOpacity="0.18" />
        </filter>
      </defs>
      <g filter="url(#lg-glow)" transform="translate(10, 10)">
        <path d="M50 12 L85 38 L85 88 L15 88 L15 38 Z" stroke="url(#lg-grad)" strokeWidth="3" fill="none" strokeLinejoin="round" />
        <path d="M50 12 L85 38" stroke="url(#lg-grad)" strokeWidth="3" strokeLinecap="round" />
        <path d="M50 12 L15 38" stroke="url(#lg-grad)" strokeWidth="3" strokeLinecap="round" />
        <rect x="38" y="60" width="24" height="28" rx="3" stroke="url(#lg-grad)" strokeWidth="2" fill="url(#lg-grad)" fillOpacity="0.1" />
        <circle cx="50" cy="48" r="6" fill="url(#lg-grad)" opacity="0.36" />
        <circle cx="50" cy="48" r="2.5" fill="url(#lg-grad)" />
      </g>
      <text x="115" y="55" fontFamily="system-ui,-apple-system,'Segoe UI',Helvetica,Arial,sans-serif" fontSize="38" fontWeight="800" letterSpacing="2">
        <tspan fill="#e2e8f0">Home</tspan><tspan fill="url(#lg-grad)">Pilot</tspan>
      </text>
      <text x="115" y="78" fontFamily="system-ui,-apple-system,'Segoe UI',Helvetica,Arial,sans-serif" fontSize="12" fill="#94a3b8" letterSpacing="2.5">YOUR AI. YOUR DATA. YOUR RULES.</text>
    </svg>
  )
}

// ── Terms of Service ────────────────────────────────────────────────────────
const TERMS_SECTIONS: Section[] = [
  {
    id: 'acceptance',
    title: '1. Acceptance of these Terms',
    body: (
      <>
        <p>
          These Terms of Service (“Terms”) govern your access to and use of the HomePilot
          software (the “Software”) and, where you choose to use it, the optional OllaBridge
          Cloud identity and relay service (the “Cloud Service”). By installing, running,
          accessing, or using the Software you agree to these Terms. If you are using HomePilot
          on behalf of an organisation, you represent that you are authorised to accept these
          Terms on its behalf.
        </p>
        <p>
          HomePilot is <strong>free and open-source software</strong>. If you do not agree with
          these Terms, do not install or use the Software.
        </p>
      </>
    ),
  },
  {
    id: 'software-license',
    title: '2. The Software and its License',
    body: (
      <>
        <p>
          The Software is licensed to you under the{' '}
          <a href={LICENSE_URL} target="_blank" rel="noopener noreferrer">Apache License, Version 2.0</a>{' '}
          (“Apache-2.0”). Your rights to use, reproduce, modify, and distribute the Software are
          governed by that license and the <code>LICENSE</code> and <code>NOTICE</code> files
          distributed with the source. In the event of any conflict between these Terms and
          Apache-2.0 with respect to the Software itself, Apache-2.0 controls.
        </p>
        <p>
          The source code is available at{' '}
          <a href={REPO_URL} target="_blank" rel="noopener noreferrer">{REPO_URL}</a>. Nothing in
          these Terms limits the rights granted to you under Apache-2.0.
        </p>
      </>
    ),
  },
  {
    id: 'self-hosted',
    title: '3. Self-Hosted, Local-First Software',
    body: (
      <>
        <p>
          HomePilot is designed to run on hardware you control (“your instance”). The person or
          organisation that operates an instance (the “Operator”) is solely responsible for that
          instance, including its configuration, security, availability, the models and providers
          it connects to, and all content processed through it.
        </p>
        <p>
          If you use a HomePilot instance operated by someone else, additional or different terms
          from that Operator may apply. The authors and contributors of the Software are not the
          Operator of your instance and do not host, access, or control your data.
        </p>
      </>
    ),
  },
  {
    id: 'accounts',
    title: '4. Accounts and Authentication',
    body: (
      <>
        <p>HomePilot supports two ways to sign in:</p>
        <ul>
          <li>
            <strong>Local accounts</strong> — created and stored on your instance. A local account
            may be passwordless (for single-user installs) or protected by a password. You are
            responsible for maintaining the confidentiality of your credentials and for all
            activity under your account.
          </li>
          <li>
            <strong>“Continue with OllaBridge”</strong> — optional federated sign-in using an
            OllaBridge Cloud account. When you use it, your identity is verified by OllaBridge
            Cloud and HomePilot provisions a linked local profile. Your use of OllaBridge Cloud is
            additionally subject to its own terms and privacy policy.
          </li>
        </ul>
        <p>
          You must provide accurate information, keep your credentials secure, and promptly notify
          the Operator of any unauthorised use. The Operator may suspend or remove accounts that
          violate these Terms.
        </p>
      </>
    ),
  },
  {
    id: 'acceptable-use',
    title: '5. Acceptable Use',
    body: (
      <>
        <p>You agree not to use the Software or Cloud Service to:</p>
        <ul>
          <li>violate any applicable law, regulation, or third-party right;</li>
          <li>infringe intellectual-property, privacy, or publicity rights;</li>
          <li>generate or distribute unlawful, harmful, or abusive content;</li>
          <li>attempt to gain unauthorised access to any system, account, or data;</li>
          <li>interfere with, disrupt, or place undue load on the Cloud Service or relay; or</li>
          <li>
            breach the terms or acceptable-use policies of any third-party model, provider, or
            service you connect to HomePilot.
          </li>
        </ul>
        <p>You are responsible for the prompts you submit and the outputs you generate and use.</p>
      </>
    ),
  },
  {
    id: 'third-party',
    title: '6. Third-Party Models, Providers, and Services',
    body: (
      <p>
        HomePilot can connect to third-party components you choose — including local model runtimes
        (e.g. Ollama), open-weight and proprietary models, external inference providers, and the
        optional OllaBridge Cloud relay. Those components are governed by their own licenses and
        terms, and may transmit the prompts and data you send to them. You are responsible for
        reviewing and complying with the terms of any component you enable. The Software’s authors
        and contributors are not responsible for third-party services or model outputs.
      </p>
    ),
  },
  {
    id: 'ai-output',
    title: '7. AI-Generated Content',
    body: (
      <p>
        Outputs produced by language and media models may be inaccurate, incomplete, or otherwise
        unsuitable for your purpose, and may not reflect the views of the Software’s authors. You
        are responsible for evaluating outputs before relying on them, and must not use them where
        failure could lead to injury, loss, or legal violation without appropriate human review.
      </p>
    ),
  },
  {
    id: 'ip',
    title: '8. Intellectual Property and Your Content',
    body: (
      <p>
        The Software is provided under Apache-2.0; product names, logos, and brands (including
        “HomePilot” and “OllaBridge”) are the property of their respective owners and are not
        licensed to you except as necessary to run and reference the Software. Content you create,
        upload, or generate on your instance remains yours; the Software’s authors claim no
        ownership of it and, for a self-hosted instance, do not receive or store it.
      </p>
    ),
  },
  {
    id: 'warranty',
    title: '9. Disclaimer of Warranties',
    body: (
      <p>
        Consistent with Section 7 of Apache-2.0, the Software and Cloud Service are provided on an{' '}
        <strong>“AS IS” and “AS AVAILABLE” basis, without warranties or conditions of any kind</strong>,
        whether express, implied, or statutory, including without limitation any warranties of
        merchantability, fitness for a particular purpose, title, and non-infringement. You bear
        the entire risk as to the quality, performance, and results of using the Software.
      </p>
    ),
  },
  {
    id: 'liability',
    title: '10. Limitation of Liability',
    body: (
      <p>
        Consistent with Section 8 of Apache-2.0, to the maximum extent permitted by law, in no
        event shall the authors, contributors, or Operators be liable for any direct, indirect,
        incidental, special, exemplary, or consequential damages (including loss of data, profits,
        or goodwill) arising out of or related to the use or inability to use the Software or Cloud
        Service, even if advised of the possibility of such damages. Some jurisdictions do not allow
        certain limitations, so some of the above may not apply to you.
      </p>
    ),
  },
  {
    id: 'changes',
    title: '11. Changes to the Software and Terms',
    body: (
      <p>
        The Software evolves continuously. The Operator or the project may modify, suspend, or
        discontinue any part of the Software or Cloud Service at any time. These Terms may be
        updated from time to time; the “Last updated” date reflects the latest revision. Continued
        use after changes take effect constitutes acceptance of the revised Terms.
      </p>
    ),
  },
  {
    id: 'governing-law',
    title: '12. Governing Law',
    body: (
      <p>
        These Terms are governed by the laws of the jurisdiction in which the Operator of your
        instance is established, without regard to conflict-of-laws principles, unless the Operator
        specifies otherwise. Nothing in these Terms limits any non-waivable statutory rights you may
        have as a consumer.
      </p>
    ),
  },
  {
    id: 'contact-terms',
    title: '13. Contact',
    body: (
      <p>
        Questions about these Terms should be directed to the Operator of the HomePilot instance you
        use. For questions about the open-source project itself, see{' '}
        <a href={REPO_URL} target="_blank" rel="noopener noreferrer">{REPO_URL}</a>.
      </p>
    ),
  },
]

// ── Privacy Policy ──────────────────────────────────────────────────────────
const PRIVACY_SECTIONS: Section[] = [
  {
    id: 'overview',
    title: '1. Overview',
    body: (
      <>
        <p>
          HomePilot is <strong>local-first</strong> software: it is designed so that your data stays
          on the instance you or your Operator runs. This Privacy Policy explains what information a
          HomePilot instance processes, why, and the choices you have.
        </p>
        <p>
          For a self-hosted instance, the <strong>Operator of that instance is the data controller</strong>.
          The authors and contributors of the open-source Software do not host your instance and do
          not receive, access, or store the data you process with it.
        </p>
      </>
    ),
  },
  {
    id: 'local-first',
    title: '2. Local-First Principle',
    body: (
      <p>
        By default, HomePilot does not send analytics or telemetry about your usage to the project
        authors. Your conversations, files, and preferences are stored on your instance. Data leaves
        your instance only when you deliberately connect it to an external service — for example a
        remote model provider, the OllaBridge Cloud relay, or federated sign-in — as described below.
      </p>
    ),
  },
  {
    id: 'data-we-process',
    title: '3. Information Processed on Your Instance',
    body: (
      <>
        <p>Depending on how you use HomePilot, your instance may process:</p>
        <ul>
          <li>
            <strong>Account data</strong> — your username, optional display name, optional email, and,
            if you set one, a password stored only as a salted <code>bcrypt</code> hash (never in
            plain text).
          </li>
          <li>
            <strong>Session data</strong> — an opaque, revocable session token stored server-side and
            issued to your browser as an <code>HttpOnly</code> cookie (<code>homepilot_session</code>)
            so you stay signed in.
          </li>
          <li>
            <strong>Your content</strong> — conversations, prompts, uploaded files, generated media,
            memory, and preferences you create while using the Software.
          </li>
          <li>
            <strong>Operational data</strong> — basic logs your Operator’s server may keep for
            security and debugging.
          </li>
        </ul>
      </>
    ),
  },
  {
    id: 'ollabridge',
    title: '4. OllaBridge Cloud (Optional Federated Sign-In)',
    body: (
      <p>
        If you choose “Continue with OllaBridge”, authentication is delegated to OllaBridge Cloud.
        In that case OllaBridge Cloud processes your OllaBridge account information (such as your
        email, email-verification status, and organisation membership) under its own privacy policy,
        and returns a verified identity to your HomePilot instance. Your instance then stores a link
        to that identity — a Cloud user identifier and your email — so it can recognise you on future
        sign-ins. If you never use OllaBridge sign-in, no such data is shared.
      </p>
    ),
  },
  {
    id: 'cookies',
    title: '5. Cookies and Local Storage',
    body: (
      <>
        <p>HomePilot uses only the storage needed to make the app work:</p>
        <ul>
          <li>
            <code>homepilot_session</code> — an <code>HttpOnly</code> session cookie used to keep you
            authenticated. It is marked <code>Secure</code> when served over HTTPS.
          </li>
          <li>
            <strong>Browser local storage</strong> — your session token, a list of recently used
            accounts (to speed up sign-in), and UI preferences, all kept in your own browser.
          </li>
        </ul>
        <p>HomePilot does not use third-party advertising or cross-site tracking cookies.</p>
      </>
    ),
  },
  {
    id: 'third-parties',
    title: '6. Third-Party Recipients',
    body: (
      <p>
        When you send a prompt to a model or provider you have configured (a local runtime such as
        Ollama, a remote inference provider, or the OllaBridge Cloud relay), the content of that
        request is transmitted to the selected service so it can produce a response. Those services
        process your data under their own terms and privacy policies. You control which services are
        enabled on your instance.
      </p>
    ),
  },
  {
    id: 'security',
    title: '7. Security',
    body: (
      <p>
        HomePilot applies sensible security defaults: passwords are hashed with <code>bcrypt</code>,
        sessions are opaque server-side tokens that can be revoked, session cookies are{' '}
        <code>HttpOnly</code> (and <code>Secure</code> over HTTPS), and per-user data is isolated at
        the data layer. No system is perfectly secure; your Operator is responsible for deploying the
        instance securely (for example, serving it over HTTPS and keeping it updated).
      </p>
    ),
  },
  {
    id: 'retention',
    title: '8. Data Retention and Deletion',
    body: (
      <p>
        Because HomePilot is self-hosted, you and your Operator control retention. Content and
        accounts persist on your instance until deleted. You can sign out to invalidate a session,
        change or set a password, and revoke other active sessions from the account settings. To
        delete an account or its data, use the instance’s account controls or contact your Operator.
      </p>
    ),
  },
  {
    id: 'children',
    title: '9. Children’s Privacy',
    body: (
      <p>
        HomePilot is not directed to children and is not intended for use by anyone under the age
        required by the laws applicable to your Operator’s jurisdiction (for example, 13 or 16). An
        Operator should not knowingly create accounts for, or collect data from, such children.
      </p>
    ),
  },
  {
    id: 'your-rights',
    title: '10. Your Rights',
    body: (
      <p>
        Depending on where you live, you may have rights to access, correct, export, or delete your
        personal data, and to object to or restrict certain processing (for example, under the GDPR
        or similar laws). Because the Operator of your instance is the data controller, you exercise
        these rights with that Operator, who can act directly on the data held on the instance.
      </p>
    ),
  },
  {
    id: 'changes-privacy',
    title: '11. Changes to this Policy',
    body: (
      <p>
        We may update this Privacy Policy as the Software evolves. The “Last updated” date reflects
        the latest revision. Material changes should be communicated by the Operator where required
        by law.
      </p>
    ),
  },
  {
    id: 'contact-privacy',
    title: '12. Contact',
    body: (
      <p>
        For privacy questions about a specific instance, contact its Operator. For questions about
        the open-source project, see{' '}
        <a href={REPO_URL} target="_blank" rel="noopener noreferrer">{REPO_URL}</a>.
      </p>
    ),
  },
]

export default function LegalPage({ kind }: { kind: LegalKind }) {
  const isTerms = kind === 'terms'
  const title = isTerms ? 'Terms of Service' : 'Privacy Policy'
  const sections = isTerms ? TERMS_SECTIONS : PRIVACY_SECTIONS
  const otherHref = isTerms ? '/privacy' : '/terms'
  const otherLabel = isTerms ? 'Privacy Policy' : 'Terms of Service'

  return (
    <div className="hp-legal">
      <style>{CSS}</style>

      <header className="hp-legal-top">
        <a href="/" className="hp-legal-brand" aria-label="Back to HomePilot sign in">
          <BrandMark />
        </a>
        <a href="/" className="hp-legal-back">← Back to sign in</a>
      </header>

      <main className="hp-legal-main">
        <div className="hp-legal-head">
          <span className="hp-legal-kicker">HomePilot · Legal</span>
          <h1>{title}</h1>
          <p className="hp-legal-updated">Last updated: {LAST_UPDATED}</p>
          <p className="hp-legal-lede">
            {isTerms
              ? 'The terms that govern your use of the HomePilot open-source software and the optional OllaBridge Cloud service.'
              : 'How a HomePilot instance handles your information — built local-first, so your data stays on your node.'}
          </p>
        </div>

        <div className="hp-legal-grid">
          <nav className="hp-legal-toc" aria-label="On this page">
            <span className="hp-legal-toc-title">On this page</span>
            <ol>
              {sections.map((s) => (
                <li key={s.id}><a href={`#${s.id}`}>{s.title}</a></li>
              ))}
            </ol>
          </nav>

          <article className="hp-legal-body">
            <div className="hp-legal-note" role="note">
              HomePilot is an Apache-2.0 open-source project. This document is a good-faith template
              for a self-hosted, local-first deployment and is provided for convenience — it is not
              legal advice. The Operator of an instance should review and adapt it for their
              jurisdiction and seek professional counsel where appropriate.
            </div>

            {sections.map((s) => (
              <section key={s.id} id={s.id} className="hp-legal-section">
                <h2>{s.title}</h2>
                {s.body}
              </section>
            ))}

            <footer className="hp-legal-foot">
              <p>
                See also the <a href={otherHref}>{otherLabel}</a>, or return to{' '}
                <a href="/">sign in</a>. Source:{' '}
                <a href={REPO_URL} target="_blank" rel="noopener noreferrer">github.com/ruslanmv/HomePilot</a>{' '}
                · Licensed under{' '}
                <a href={LICENSE_URL} target="_blank" rel="noopener noreferrer">Apache-2.0</a>.
              </p>
            </footer>
          </article>
        </div>
      </main>
    </div>
  )
}

const CSS = `
.hp-legal { --bg:#020307; --ink:#f8fafc; --ink-2:rgba(226,232,240,.72); --ink-3:rgba(148,163,184,.62);
  --cyan:#06b6d4; --blue:#3b82f6; --violet:#8b5cf6; --line:rgba(255,255,255,.08);
  --font:Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  position:fixed; inset:0; overflow:auto; background:
    radial-gradient(circle at 12% 8%, rgba(6,182,212,.05), transparent 30%),
    radial-gradient(circle at 88% 4%, rgba(139,92,246,.05), transparent 32%), var(--bg);
  color:var(--ink); font-family:var(--font); -webkit-font-smoothing:antialiased; }
.hp-legal *, .hp-legal *::before, .hp-legal *::after { box-sizing:border-box; }
.hp-legal a { color:#a78bfa; text-decoration:none; }
.hp-legal a:hover { color:#fff; text-decoration:underline; }

.hp-legal-top { position:sticky; top:0; z-index:5; display:flex; align-items:center; justify-content:space-between;
  gap:16px; padding:16px clamp(20px,5vw,56px); background:rgba(2,3,7,.72);
  -webkit-backdrop-filter:blur(12px); backdrop-filter:blur(12px); border-bottom:1px solid var(--line); }
.hp-legal-brand { display:inline-flex; }
.hp-legal-logo { width:180px; height:54px; display:block; }
.hp-legal-back { font-size:14px; font-weight:600; white-space:nowrap; }

.hp-legal-main { max-width:1080px; margin:0 auto; padding:clamp(28px,5vw,56px) clamp(20px,5vw,56px) 80px; }
.hp-legal-head { border-bottom:1px solid var(--line); padding-bottom:26px; margin-bottom:34px; }
.hp-legal-kicker { display:inline-block; font-size:12px; font-weight:700; letter-spacing:.14em; text-transform:uppercase;
  color:transparent; background:linear-gradient(90deg,var(--cyan),var(--blue),var(--violet));
  -webkit-background-clip:text; background-clip:text; }
.hp-legal-head h1 { margin:12px 0 10px; font-size:clamp(32px,5vw,46px); font-weight:720; letter-spacing:-.03em; line-height:1.05; }
.hp-legal-updated { margin:0 0 14px; color:var(--ink-3); font-size:13px; }
.hp-legal-lede { margin:0; max-width:60ch; color:var(--ink-2); font-size:clamp(16px,1.4vw,18px); line-height:1.55; }

.hp-legal-grid { display:grid; grid-template-columns:minmax(0,1fr); gap:40px; }
@media (min-width:960px) { .hp-legal-grid { grid-template-columns:250px minmax(0,1fr); } }

.hp-legal-toc { align-self:start; }
@media (min-width:960px) { .hp-legal-toc { position:sticky; top:96px; } }
.hp-legal-toc-title { display:block; font-size:12px; font-weight:700; letter-spacing:.1em; text-transform:uppercase;
  color:var(--ink-3); margin-bottom:12px; }
.hp-legal-toc ol { list-style:none; margin:0; padding:0; display:grid; gap:2px; border-left:1px solid var(--line); }
.hp-legal-toc li a { display:block; padding:7px 14px; font-size:13.5px; color:var(--ink-3); line-height:1.35;
  border-left:2px solid transparent; margin-left:-1px; transition:color .18s, border-color .18s; }
.hp-legal-toc li a:hover { color:#fff; border-left-color:var(--blue); text-decoration:none; }

.hp-legal-body { min-width:0; max-width:76ch; }
.hp-legal-note { margin:0 0 30px; padding:14px 16px; border-radius:14px; font-size:13.5px; line-height:1.55;
  color:var(--ink-2); background:linear-gradient(180deg, rgba(59,130,246,.08), rgba(139,92,246,.05));
  border:1px solid rgba(99,102,241,.22); }
.hp-legal-section { padding:22px 0; border-top:1px solid var(--line); scroll-margin-top:96px; }
.hp-legal-section:first-of-type { border-top:0; padding-top:0; }
.hp-legal-section h2 { margin:0 0 12px; font-size:20px; font-weight:680; letter-spacing:-.01em; color:#fff; }
.hp-legal-section p { margin:0 0 12px; color:var(--ink-2); font-size:15.5px; line-height:1.68; }
.hp-legal-section ul { margin:0 0 12px; padding-left:20px; display:grid; gap:8px; }
.hp-legal-section li { color:var(--ink-2); font-size:15.5px; line-height:1.6; }
.hp-legal-section strong { color:#f1f5f9; font-weight:650; }
.hp-legal-section code { font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; font-size:.9em;
  padding:1px 6px; border-radius:6px; background:rgba(255,255,255,.06); border:1px solid var(--line); color:#c7d2fe; }
.hp-legal-foot { margin-top:34px; padding-top:22px; border-top:1px solid var(--line); }
.hp-legal-foot p { margin:0; color:var(--ink-3); font-size:13.5px; line-height:1.6; }

@media (max-width:520px) {
  .hp-legal-logo { width:150px; height:46px; }
  .hp-legal-section p, .hp-legal-section li { font-size:15px; }
}
`
