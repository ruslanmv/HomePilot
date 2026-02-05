import { useEffect, useState, useRef } from 'react'

export default function Typewriter({ text, speed = 14 }: { text: string, speed?: number }) {
  const [out, setOut] = useState('')
  const indexRef = useRef(0)
  const speedRef = useRef(speed)

  // Update speed without restarting typing
  useEffect(() => {
    speedRef.current = speed
  }, [speed])

  // Restart typing ONLY when text changes (speed removed from deps)
  useEffect(() => {
    setOut('')
    indexRef.current = 0
    const t = setInterval(() => {
      indexRef.current++
      setOut(text.slice(0, indexRef.current))
      if (indexRef.current >= text.length) clearInterval(t)
    }, speedRef.current)
    return () => clearInterval(t)
  }, [text]) // speed removed - uses speedRef instead

  return <span>{out}</span>
}
