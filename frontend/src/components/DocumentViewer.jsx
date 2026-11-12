export default function DocumentViewer({ doc, onClose }) {
  if (!doc) return null

  function handleDownloadMeta() {
    const filename = doc.name || 'document'
    const baseName = filename.replace(/\.[^/.]+$/, "")
    const metaObj = {
      filename: doc.name,
      ...(doc.rawMeta || {}),
      exported_at: new Date().toISOString()
    }
    const blob = new Blob([JSON.stringify(metaObj, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${baseName}_lens_audit.json`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }

  return (
    <aside className="docViewer" aria-label="Document viewer">
      <div className="docViewerHead">
        <div className="docViewerTitle">
          <span aria-hidden="true">📄</span>
          <b title={doc.name}>{doc.name}</b>
        </div>
        <div className="docViewerActions">
          <button type="button" className="docViewerBtn" onClick={handleDownloadMeta} title="Download audit metadata as JSON">
            Meta ⤓
          </button>
          {doc.viewUrl && (
            <a className="docViewerBtn" href={doc.viewUrl} target="_blank" rel="noreferrer" title="Open in new tab">
              New tab ↗
            </a>
          )}
          {doc.downloadUrl && (
            <a className="docViewerBtn" href={doc.downloadUrl} title="Download original file">
              Download ⤓
            </a>
          )}
          <button type="button" className="docViewerBtn close" onClick={onClose} aria-label="Close viewer">✕</button>
        </div>
      </div>

      <div className="docViewerBody">
        {doc.viewUrl ? (
          <iframe className="docViewerFrame" src={doc.viewUrl} title={doc.name} />
        ) : (
          <div className="docViewerFallback">
            <p className="docViewerNote">
              {doc.preview ? "Preview rendering from extracted text content below:" : "Document loaded. Use the actions above to view or download."}
            </p>
            {doc.preview && (
              <pre className="docPreviewContent">{doc.preview}</pre>
            )}
          </div>
        )}
      </div>
    </aside>
  )
}

