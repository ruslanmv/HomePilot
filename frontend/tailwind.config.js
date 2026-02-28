/** @type {import('tailwindcss').Config} */
export default {
content: ["./index.html", "./src/**/*.{ts,tsx}"],
theme: {
extend: {
boxShadow: { soft: "0 10px 30px rgba(0,0,0,0.35)" },
keyframes: {
floaty: { "0%,100%": { transform: "translateY(0)" }, "50%": { transform: "translateY(-4px)" } },
fadeIn: { from: { opacity: "0", transform: "translateY(2px)" }, to: { opacity: "1", transform: "translateY(0)" } },
/* ── Teams Meeting Animations ── */
speakingRing: {
  "0%": { boxShadow: "0 0 0 0 rgba(52, 211, 153, 0.5)", transform: "scale(1)" },
  "50%": { boxShadow: "0 0 0 10px rgba(52, 211, 153, 0)", transform: "scale(1.04)" },
  "100%": { boxShadow: "0 0 0 0 rgba(52, 211, 153, 0)", transform: "scale(1)" },
},
wantsToSpeakPulse: {
  "0%": { boxShadow: "0 0 0 0 rgba(251, 191, 36, 0.35)" },
  "70%": { boxShadow: "0 0 0 5px rgba(251, 191, 36, 0)" },
  "100%": { boxShadow: "0 0 0 0 rgba(251, 191, 36, 0)" },
},
seatBreathe: {
  "0%,100%": { transform: "scale(1)", opacity: "1" },
  "50%": { transform: "scale(1.015)", opacity: "0.92" },
},
msgSlideIn: {
  "0%": { opacity: "0", transform: "translateY(12px) scale(0.97)" },
  "100%": { opacity: "1", transform: "translateY(0) scale(1)" },
},
msgSlideInRight: {
  "0%": { opacity: "0", transform: "translateX(12px) scale(0.97)" },
  "100%": { opacity: "1", transform: "translateX(0) scale(1)" },
},
seatEnter: {
  "0%": { opacity: "0", transform: "translate(-50%, -50%) scale(0.85)" },
  "60%": { opacity: "1", transform: "translate(-50%, -50%) scale(1.04)" },
  "100%": { opacity: "1", transform: "translate(-50%, -50%) scale(1)" },
},
eqBar: {
  "0%,100%": { height: "20%" },
  "50%": { height: "90%" },
},
thinkWave: {
  "0%,60%,100%": { transform: "translateY(0)" },
  "30%": { transform: "translateY(-6px)" },
},
confidenceFill: {
  "0%": { width: "0%" },
  "100%": { width: "var(--confidence-width)" },
},
badgeIn: {
  "0%": { opacity: "0", transform: "translate(-50%, 0) scale(0.5)" },
  "100%": { opacity: "1", transform: "translate(-50%, 0) scale(1)" },
},
glowPulse: {
  "0%,100%": { opacity: "0.6" },
  "50%": { opacity: "1" },
},
/* ── Teams V2 Layout Animations ── */
railSlideLeft: {
  "0%": { opacity: "0", transform: "translateX(-16px)" },
  "100%": { opacity: "1", transform: "translateX(0)" },
},
railSlideRight: {
  "0%": { opacity: "0", transform: "translateX(16px)" },
  "100%": { opacity: "1", transform: "translateX(0)" },
},
agendaCheck: {
  "0%": { transform: "scale(0.8)" },
  "50%": { transform: "scale(1.15)" },
  "100%": { transform: "scale(1)" },
},
seatSwap: {
  "0%": { opacity: "0.5", transform: "translate(-50%, -50%) scale(0.9)" },
  "60%": { opacity: "1", transform: "translate(-50%, -50%) scale(1.03)" },
  "100%": { opacity: "1", transform: "translate(-50%, -50%) scale(1)" },
},
stripSlide: {
  "0%": { opacity: "0", transform: "translateY(8px)" },
  "100%": { opacity: "1", transform: "translateY(0)" },
},
tabUnderline: {
  "0%": { width: "0%", opacity: "0" },
  "100%": { width: "100%", opacity: "1" },
},
},
animation: {
floaty: "floaty 2.2s ease-in-out infinite",
fadeIn: "fadeIn 160ms ease-out",
/* ── Teams Meeting Animations ── */
"speaking-ring": "speakingRing 1.8s ease-in-out infinite",
"wants-pulse": "wantsToSpeakPulse 2s ease-out infinite",
"seat-breathe": "seatBreathe 3.5s ease-in-out infinite",
"msg-slide-in": "msgSlideIn 320ms cubic-bezier(0.21, 1.02, 0.73, 1)",
"msg-slide-in-right": "msgSlideInRight 320ms cubic-bezier(0.21, 1.02, 0.73, 1)",
"seat-enter": "seatEnter 450ms cubic-bezier(0.34, 1.56, 0.64, 1)",
"eq-bar": "eqBar 0.8s ease-in-out infinite",
"think-wave": "thinkWave 1.2s ease-in-out infinite",
"confidence-fill": "confidenceFill 600ms ease-out forwards",
"badge-in": "badgeIn 250ms cubic-bezier(0.34, 1.56, 0.64, 1)",
"glow-pulse": "glowPulse 2s ease-in-out infinite",
/* ── Teams V2 Layout Animations ── */
"rail-slide-left": "railSlideLeft 250ms cubic-bezier(0.21, 1.02, 0.73, 1)",
"rail-slide-right": "railSlideRight 250ms cubic-bezier(0.21, 1.02, 0.73, 1)",
"agenda-check": "agendaCheck 300ms cubic-bezier(0.34, 1.56, 0.64, 1)",
"seat-swap": "seatSwap 350ms cubic-bezier(0.34, 1.56, 0.64, 1)",
"strip-slide": "stripSlide 280ms ease-out",
"tab-underline": "tabUnderline 200ms ease-out forwards",
}
}
},
plugins: []
}
