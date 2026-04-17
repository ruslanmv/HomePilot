// showcase.jsx — designer review canvas.
//
// Load this in the same DesignCanvas your reference files already use
// (iOS/Android/Chrome/macOS frames). It lays out every state of every
// piece of the HomePilot call UI on a single Figma-like board, with
// post-it callouts so design + dev see the same expectations.
//
// Sections, top to bottom:
//   1. Header Call button — 5 states (rest, hover, dialing,
//      in-call, in-call-hover) with 📞 first-time tooltip variant.
//   2. Full Call Modal — 5 states (connecting, listening, thinking,
//      speaking, muted) shown both standalone and over the blurred
//      backdrop.
//   3. Picture-in-picture — 4 states of the minimized dock.
//   4. In-context — the modal inside a macOS window + iOS + Android
//      frames so designer can eyeball platform fidelity.
//
// Requires (loaded in this order in the host page):
//   react + react-dom
//   design-canvas.jsx
//   ios-frame.jsx · android-frame.jsx · macos-window.jsx
//   tokens.jsx · icons.jsx · controls.jsx · avatar.jsx · waveform.jsx
//   call-button.jsx · call-modal.jsx · call-pip.jsx · first-time-tooltip.jsx

function HPCallShowcase() {
  return (
    <DesignCanvas>
      {/* ────────────────────────── Section 1 ────────────────────────── */}
      <DCSection
        title="Header call button"
        subtitle="Top-right of the Voice page, 36 px, before the gear. Emerald at rest, red mid-call — same pixel position across states."
      >
        <DCArtboard label="1 · rest" width={220} height={120}>
          <div style={cellStyle}>
            <HPCallButton state="rest" />
          </div>
        </DCArtboard>
        <DCArtboard label="2 · hover" width={220} height={120}>
          <div style={cellStyle}>
            <HPCallButton state="hover" />
          </div>
        </DCArtboard>
        <DCArtboard label="3 · dialing (300 ms crossfade)" width={220} height={120}>
          <div style={cellStyle}>
            <HPCallButton state="dialing" />
          </div>
        </DCArtboard>
        <DCArtboard label="4 · in-call" width={220} height={120}>
          <div style={cellStyle}>
            <HPCallButton state="inCall" />
          </div>
        </DCArtboard>
        <DCArtboard label="5 · in-call · hover" width={220} height={120}>
          <div style={cellStyle}>
            <HPCallButton state="inCallHover" />
          </div>
        </DCArtboard>
        <DCArtboard label="6 · first-time tooltip" width={240} height={180}>
          <div style={{ ...cellStyle, gap: 4 }}>
            <HPCallButton state="rest" />
            <HPCallFirstTimeTooltip visible text="Talk live" />
          </div>
        </DCArtboard>

        <DCPostIt top={20} right={30} rotate={4} width={200}>
          Diameter 36 px · +15 % over the gear (32 px). Halo grows from 6 → 8 px on hover. Tooltip auto-dismisses after 4 s.
        </DCPostIt>
      </DCSection>

      {/* ────────────────────────── Section 1b ────────────────────────── */}
      <DCSection
        title="Header context"
        subtitle="Standalone 📞 separated from the ⚙ ✏ group by 12 px so it reads as primary, not utility."
      >
        <DCArtboard label="rest" width={540} height={80}>
          <HPCallHeaderMock state="rest" />
        </DCArtboard>
        <DCArtboard label="in-call" width={540} height={80}>
          <HPCallHeaderMock state="inCall" />
        </DCArtboard>
      </DCSection>

      {/* ────────────────────────── Section 2 ────────────────────────── */}
      <DCSection
        title="Call modal · state set"
        subtitle="Same card, five states. Halo + waveform + label color are the only things that change."
      >
        {['connecting', 'listening', 'thinking', 'speaking', 'muted'].map((s) => (
          <DCArtboard key={s} label={s} width={460} height={560}>
            <div style={modalCell}>
              <HPCallModal
                state={s}
                personaName="Darkangel666"
                durationSec={20}
              />
            </div>
          </DCArtboard>
        ))}

        <DCPostIt top={-8} right={60} rotate={-3} width={220}>
          Halo color = state color. Waveform & label pull from the same token so adding a 6th state is ~2 token lines.
        </DCPostIt>
      </DCSection>

      {/* ────────────────────────── Section 2b — Presentation ────────── */}
      <DCSection
        title="Call modal · over blurred chat"
        subtitle="Backdrop-blur + state-color wash behind the modal — how the user actually sees it."
      >
        <DCArtboard label="listening · in situ" width={800} height={520}>
          <HPCallModalPresentation
            state="listening"
            personaName="Darkangel666"
            durationSec={20}
          />
        </DCArtboard>
        <DCArtboard label="speaking · in situ" width={800} height={520}>
          <HPCallModalPresentation
            state="speaking"
            personaName="Darkangel666"
            durationSec={42}
          />
        </DCArtboard>
      </DCSection>

      {/* ────────────────────────── Section 3 ────────────────────────── */}
      <DCSection
        title="Picture-in-picture"
        subtitle="Minimize → this pill floats bottom-right until the user taps back in (re-opens modal) or hangs up (red disc)."
      >
        {['connecting', 'listening', 'speaking', 'muted'].map((s) => (
          <DCArtboard key={s} label={s} width={320} height={120}>
            <div style={pipCell}>
              <HPCallPip state={s} personaName="Darkangel666" durationSec={134} />
            </div>
          </DCArtboard>
        ))}
      </DCSection>

      {/* ────────────────────────── Section 4 — Platform frames ──────── */}
      <DCSection
        title="In-context across devices"
        subtitle="Same component dropped into iOS / Android / macOS frames — no per-platform assets."
      >
        <DCArtboard label="iOS" width={402} height={874}>
          <IOSDevice dark>
            <div style={deviceCell}>
              <HPCallModal
                state="listening"
                personaName="Darkangel666"
                durationSec={20}
                width={360}
              />
            </div>
          </IOSDevice>
        </DCArtboard>

        <DCArtboard label="Android" width={412} height={892}>
          <AndroidDevice dark>
            <div style={deviceCell}>
              <HPCallModal
                state="speaking"
                personaName="Darkangel666"
                durationSec={58}
                width={368}
              />
            </div>
          </AndroidDevice>
        </DCArtboard>

        <DCArtboard label="macOS" width={900} height={600}>
          <MacWindow
            title="HomePilot — Voice"
            sidebar={<div />}
          >
            <div style={{ ...deviceCell, padding: 40 }}>
              <HPCallModal
                state="muted"
                personaName="Darkangel666"
                durationSec={112}
              />
            </div>
          </MacWindow>
        </DCArtboard>
      </DCSection>
    </DesignCanvas>
  );
}

// ── Cell helpers — center the component inside a dark art-board ─────
const cellStyle = {
  width: '100%', height: '100%',
  background: '#050506',
  display: 'flex', alignItems: 'center', justifyContent: 'center',
  flexDirection: 'column',
};
const modalCell = {
  ...cellStyle,
  padding: 20, background: '#050506',
};
const pipCell = {
  ...cellStyle,
  padding: 12, background: '#050506',
};
const deviceCell = {
  width: '100%', height: '100%',
  display: 'flex', alignItems: 'center', justifyContent: 'center',
  background: '#050506',
};

Object.assign(window, { HPCallShowcase });
