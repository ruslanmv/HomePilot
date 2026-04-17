// controls.jsx — the circular action button shared by the modal, the
// PIP, and the header's mid-call end state.
//
// Three physical sizes in the call UI:
//   • 48 px  — secondary actions (mic toggle, text toggle)
//   • 56 px  — the modal's primary actions in a three-button layout
//   • 72 px  — the solo hang-up button (biggest, most visible)
//
// Two color treatments:
//   • neutral (glassy white-10 over dark surface) — mic, text, back
//   • solid  (danger / start) — hang-up + answer / call back
//
// `active` overrides the neutral treatment with a filled pill (for
// "muted" state on the mic button: filled means ON).

function HPControlBtn({
  size = 48,
  tone = 'neutral',      // 'neutral' | 'danger' | 'start' | 'accent'
  active = false,        // filled-state rendering for toggles
  disabled = false,
  label,                 // lowercase microcopy under the button
  ariaLabel,
  children,
}) {
  const bg = (
    tone === 'danger' ? HP_CALL.end
    : tone === 'start' ? HP_CALL.start
    : tone === 'accent' ? HP_CALL.accent
    : (active ? 'rgba(255,255,255,0.92)' : HP_CALL.surface2)
  );
  const fg = (
    tone === 'danger' || tone === 'start' ? '#ffffff'
    : tone === 'accent' ? '#052c33'
    : (active ? '#0b0b0c' : HP_CALL.text)
  );
  const glow = (
    tone === 'danger' ? 'rgba(239, 68, 68, 0.45)'
    : tone === 'start' ? 'rgba(16, 185, 129, 0.45)'
    : tone === 'accent' ? 'rgba(34, 211, 238, 0.4)'
    : 'rgba(0, 0, 0, 0.3)'
  );
  const border = (
    tone === 'neutral' && !active
      ? `1px solid ${HP_CALL.border}`
      : 'none'
  );

  return (
    <div style={{
      display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6,
      opacity: disabled ? 0.45 : 1,
      cursor: disabled ? 'not-allowed' : 'pointer',
    }}>
      <div
        role="button"
        aria-label={ariaLabel || label || ''}
        style={{
          width: size, height: size, borderRadius: '50%',
          background: bg,
          border,
          color: fg,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          boxShadow:
            tone === 'neutral' && !active
              ? 'inset 0 1px 0 rgba(255,255,255,0.04)'
              : `0 8px 22px ${glow}, inset 0 1px 0 rgba(255,255,255,0.12)`,
          transition: 'transform 80ms ease, background 120ms ease, box-shadow 120ms ease',
        }}
      >
        {children}
      </div>
      {label ? (
        <span style={{
          fontFamily: HP_CALL.font,
          fontSize: 11, fontWeight: 500, letterSpacing: 0.2,
          color: HP_CALL.text3, textTransform: 'lowercase',
        }}>{label}</span>
      ) : null}
    </div>
  );
}

Object.assign(window, { HPControlBtn });
