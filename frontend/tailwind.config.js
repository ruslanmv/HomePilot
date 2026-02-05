/** @type {import('tailwindcss').Config} */
export default {
content: ["./index.html", "./src/**/*.{ts,tsx}"],
theme: {
extend: {
boxShadow: { soft: "0 10px 30px rgba(0,0,0,0.35)" },
keyframes: {
floaty: { "0%,100%": { transform: "translateY(0)" }, "50%": { transform: "translateY(-4px)" } },
fadeIn: { from: { opacity: "0", transform: "translateY(2px)" }, to: { opacity: "1", transform: "translateY(0)" } }
},
animation: {
floaty: "floaty 2.2s ease-in-out infinite",
fadeIn: "fadeIn 160ms ease-out"
}
}
},
plugins: []
}
