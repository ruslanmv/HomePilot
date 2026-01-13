/** @type {import('tailwindcss').Config} */
export default {
content: ["./index.html", "./src/**/*.{ts,tsx}"],
theme: {
extend: {
boxShadow: { soft: "0 10px 30px rgba(0,0,0,0.35)" },
keyframes: {
floaty: { "0%,100%": { transform: "translateY(0)" }, "50%": { transform: "translateY(-4px)" } }
},
animation: { floaty: "floaty 2.2s ease-in-out infinite" }
}
},
plugins: []
}
