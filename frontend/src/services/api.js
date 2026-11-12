const API_BASE = import.meta.env.VITE_API_BASE || ''

export async function reviewContent({ file, text, conversationHistory = [] }) {
  const formData = new FormData()
  if (file) {
    formData.append('file', file)
  }
  if (text) {
    formData.append('text', text)
  }
  formData.append('conversation_history', JSON.stringify(conversationHistory))

  const res = await fetch(`${API_BASE}/api/review`, {
    method: 'POST',
    body: formData,
  })

  if (!res.ok) {
    const errText = await res.text()
    try {
      const errJson = JSON.parse(errText)
      throw new Error(errJson.detail || errJson.message || `Request failed with status ${res.status}`)
    } catch {
      throw new Error(errText || `Server error (${res.status})`)
    }
  }

  return await res.json()
}

export function toViewerDoc(meta) {
  if (!meta) return null
  const abs = u => (u ? (u.startsWith('http') ? u : `${API_BASE}${u}`) : null)

  const viewUrl = abs(meta.view_url || meta.viewUrl)
  const downloadUrl = abs(meta.url || meta.downloadUrl)

  return {
    name: meta.filename || meta.name || 'Document',
    viewUrl: viewUrl,
    downloadUrl: downloadUrl,
    preview: meta.preview || '',
    rawMeta: meta,
  }
}

