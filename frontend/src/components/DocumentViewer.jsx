export default function DocumentViewer({ doc, onClose }) {
  if (!doc) return null

  function handleDownloadMeta() {
    const filename = doc.name || 'document'
    const baseName = filename.replace(/\.[^/.]+$/, '')
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
          <svg className="icon" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
            <polyline points="14 2 14 8 20 8" />
          </svg>
          <b title={doc.name}>{doc.name}</b>
        </div>
        <div className="docViewerActions">
          <button type="button" className="docViewerBtn" onClick={handleDownloadMeta} title="Download audit metadata as JSON">
            <span>Meta</span>
          </button>
          {doc.viewUrl && (
            <a className="docViewerBtn" href={doc.viewUrl} target="_blank" rel="noreferrer" title="Open in new tab">
              <span>New Tab</span>
            </a>
          )}
          {doc.downloadUrl && (
            <a className="docViewerBtn" href={doc.downloadUrl} download={doc.name} title="Download file">
              <span>Download</span>
            </a>
          )}
          <button type="button" className="docViewerBtn close" onClick={onClose} aria-label="Close viewer">
            <svg className="icon" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>
      </div>

      <div className="docViewerBody">
        {doc.viewUrl ? (
          <iframe className="docViewerFrame" src={doc.viewUrl} title={doc.name} />
        ) : (
          <div className="docViewerFallback">
            <p className="docViewerNote">
              {doc.preview ? 'Preview rendering from extracted text content below:' : 'Document loaded. Use the actions above to view or download.'}
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
