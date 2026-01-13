import { useEffect, useState } from 'react'

export default function Typewriter({ text, speed = 14 }: { text: string, speed?: number }) {
const [out, setOut] = useState('')

useEffect(() => {
setOut('')
let i = 0
const t = setInterval(() => {
i++
setOut(text.slice(0, i))
if (i >= text.length) clearInterval(t)
}, speed)
return () => clearInterval(t)
}, [text, speed])

return <span>{out}</span>
}
