/**
 * One sentence from GET /v1/edition for a sidebar tab on the hosted Space.
 * Local installs render nothing: those machines run the tab themselves.
 */
import { useEffect, useState } from 'react'
import { getEdition } from './edition'

export function HostedTabNote({ tabId }: { tabId: string }) {
  const [text, setText] = useState('')
  useEffect(() => {
    let live = true
    getEdition().then((ed) => {
      if (!live || !ed.is_web) return
      const row = ed.tabs.find((t) => t.id === tabId)
      if (row?.works) setText(row.works)
    }).catch(() => { /* edition is optional copy */ })
    return () => { live = false }
  }, [tabId])
  if (!text) return null
  return <p className="text-[12px] leading-relaxed text-white/45 max-w-xl">{text}</p>
}
