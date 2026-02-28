/**
 * useTeamsDocuments — hook for shared document CRUD against the Teams backend.
 *
 * Additive — does not modify any existing hooks or state.
 */

import type { TeamDocument, MeetingRoom } from './types'

export function useTeamsDocuments(backendUrl: string, apiKey?: string) {
  const headers: Record<string, string> = {}
  if (apiKey) headers['x-api-key'] = apiKey

  async function list(roomId: string): Promise<TeamDocument[]> {
    const res = await fetch(`${backendUrl}/v1/teams/rooms/${roomId}/documents`, { headers })
    if (!res.ok) throw new Error(`Failed to list documents: ${res.status}`)
    return res.json()
  }

  async function upload(
    roomId: string,
    file: File,
    uploadedBy = 'You',
  ): Promise<{ room: MeetingRoom; document: TeamDocument }> {
    const form = new FormData()
    form.append('file', file)
    form.append('uploaded_by', uploadedBy)
    const res = await fetch(`${backendUrl}/v1/teams/rooms/${roomId}/documents/upload`, {
      method: 'POST',
      headers,
      body: form,
    })
    if (!res.ok) throw new Error(`Failed to upload: ${res.status}`)
    return res.json()
  }

  async function addUrl(
    roomId: string,
    url: string,
    title = '',
  ): Promise<{ room: MeetingRoom; document: TeamDocument }> {
    const res = await fetch(`${backendUrl}/v1/teams/rooms/${roomId}/documents/url`, {
      method: 'POST',
      headers: { ...headers, 'content-type': 'application/json' },
      body: JSON.stringify({ url, title }),
    })
    if (!res.ok) throw new Error(`Failed to add url: ${res.status}`)
    return res.json()
  }

  async function preview(roomId: string, docId: string): Promise<string> {
    const res = await fetch(
      `${backendUrl}/v1/teams/rooms/${roomId}/documents/${docId}/preview`,
      { headers },
    )
    if (!res.ok) throw new Error(`Failed to preview: ${res.status}`)
    const data = await res.json()
    return data.preview as string
  }

  async function download(roomId: string, doc: TeamDocument): Promise<void> {
    const res = await fetch(
      `${backendUrl}/v1/teams/rooms/${roomId}/documents/${doc.id}/download`,
      { headers },
    )
    if (!res.ok) throw new Error('Download failed')
    const blob = await res.blob()
    const href = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = href
    a.download = doc.name || 'document'
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(href)
  }

  async function deleteDoc(roomId: string, docId: string): Promise<MeetingRoom> {
    const res = await fetch(`${backendUrl}/v1/teams/rooms/${roomId}/documents/${docId}`, {
      method: 'DELETE',
      headers,
    })
    if (!res.ok) throw new Error(`Failed to delete: ${res.status}`)
    return res.json()
  }

  return { list, upload, addUrl, preview, download, deleteDoc }
}
