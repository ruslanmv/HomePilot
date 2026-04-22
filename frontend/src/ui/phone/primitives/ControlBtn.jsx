/**
 * ControlBtn — circular control button shared by CallScreen's action
 * dock, the CallModal's three-button row, and PostCallCard's
 * secondary actions.
 *
 * Three tones map to the three kinds of actions on the call surface:
 *
 *   neutral  default — mic, speaker, chat, video (secondary)
 *   active   a toggle is ON — mute, speaker-on (muted/amber state)
 *   danger   end-call / decline (destructive, always visually
 *            dominant)
 *
 * Three sizes cover the layout needs the handoff specifies:
 *
 *   sm (48 px)   tertiary controls (message, speaker) inside a
 *                 larger dock
 *   md (60 px)   the normal modal three-button layout
 *   lg (72 px)   solo hang-up on an accept/decline row
 *
 * All sizes respect a 44×44 minimum hit target (WCAG 2.5.5) — the
 * 48 px 'sm' floor handles it implicitly; 'md' and 'lg' are above
 * the floor by design.
 *
 * Every button carries an ``aria-label`` derived from ``label``,
 * and a visible caption below unless ``showLabel`` is false (for
 * the tight 3-up layout in CallModal where captions would wrap).
 */
import React from 'react';
import { CALL } from '../tokens';
const SIZES = {
    sm: 48,
    md: 60,
    lg: 72,
};
function toneStyles(tone) {
    switch (tone) {
        case 'danger':
            return {
                background: CALL.danger,
                color: '#0c0810',
                border: 'none',
                shadow: '0 8px 22px rgba(0, 0, 0, 0.35)',
            };
        case 'active':
            return {
                background: `color-mix(in oklch, ${CALL.amber} 28%, transparent)`,
                color: CALL.amber,
                border: `0.5px solid color-mix(in oklch, ${CALL.amber} 55%, transparent)`,
                shadow: 'inset 0 1px 0 rgba(255,255,255,0.04)',
            };
        case 'neutral':
        default:
            return {
                background: 'rgba(245,236,255,0.08)',
                color: CALL.ink,
                border: `0.5px solid ${CALL.line}`,
                shadow: 'inset 0 1px 0 rgba(255,255,255,0.04)',
            };
    }
}
const ControlBtn = ({ icon, label, onClick, tone = 'neutral', size = 'md', disabled = false, showLabel = true, pressed, className, }) => {
    const px = SIZES[size];
    const t = toneStyles(tone);
    return (<div className={className} style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap: 6,
        }}>
      <button type="button" onClick={disabled ? undefined : onClick} disabled={disabled} aria-label={label} aria-pressed={pressed} style={{
            width: px,
            height: px,
            borderRadius: '50%',
            background: t.background,
            color: t.color,
            border: t.border,
            boxShadow: t.shadow,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: 0,
            cursor: disabled ? 'not-allowed' : 'pointer',
            opacity: disabled ? 0.45 : 1,
            transition: 'transform 100ms ease, background 120ms ease, box-shadow 120ms ease',
            // Tailwind's global preflight doesn't reach inline styles;
            // we set a specific font-family so captions/icons inherit
            // the right family even if the button is rendered outside
            // a phone-typography context.
            fontFamily: CALL.font,
        }}>
        {icon}
      </button>
      {showLabel ? (<span style={{
                fontSize: 11,
                fontWeight: 500,
                letterSpacing: 0.2,
                color: CALL.dim,
                textTransform: 'lowercase',
                userSelect: 'none',
            }}>
          {label}
        </span>) : null}
    </div>);
};
export default ControlBtn;
