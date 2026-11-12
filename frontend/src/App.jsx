import { useState, useEffect, useRef } from 'react'
import LensSidebar from './components/LensSidebar.jsx'
import LensResultCard from './components/LensResultCard.jsx'
import DocumentViewer from './components/DocumentViewer.jsx'
import { reviewContent, toViewerDoc } from './services/api.js'

const STORAGE_KEY = 'lens_audits_v1'

const GENERIC_GREETINGS = new Set([
  'hi', 'hello', 'hey', 'ji', 'hlo', 'yo', 'sup', 'namaste', 'hola', 'greetings',
  'good morning', 'good afternoon', 'good evening', 'how are you', 'how are u',
  'how r u', 'hows it going', 'whats up', 'ok', 'okay', 'thanks', 'thank you'
])

function isGreeting(text) {
  if (!text) return true
  const clean = text.trim().toLowerCase().replace(/[^\w\s]/g, '').replace(/\s+/g, ' ')
  if (clean.length <= 2) return true
  if (GENERIC_GREETINGS.has(clean)) return true
  return /^(?:hi+|h[ea]y+|h[ea]llo+|hlo|hola|greetings?|yo+|sup|namaste)(?:\s+(?:there|lens|agent|bot|all|team|friend|buddy))?$/.test(clean) ||
         /^(?:(?:hi+|h[ea]y+|h[ea]llo+|hlo)\s+)?(?:how|hw)\s+(?:r|are|re)\s+(?:u|you|yu)(?:\s+doing)?$/.test(clean) ||
         /^(?:hru|whats?\s+up|hows?\s+it\s+going|hows?\s+u)$/.test(clean)
}

function shorten(str, max = 38) {
  if (!str) return ''
  return str.length > max ? str.slice(0, max).trim() + '...' : str
}

function cleanTitle(str) {
  if (!str) return ''
  return str.trim().split(' ').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ')
}

function deriveSmartTitle(userText, fileName, aiResponse) {
  // 1. If AI response has a topic or summary
  if (aiResponse && aiResponse.type !== 'chat') {
    const summary = aiResponse.publish_readiness?.summary
    if (summary) {
      const matchQuote = summary.match(/['"]([^'"]+)['"]/i)
      if (matchQuote && matchQuote[1].length > 3 && matchQuote[1].length < 40) {
        return shorten(cleanTitle(matchQuote[1]), 40)
      }
      const matchFor = summary.match(/(?:audit|review|assessment)\s+(?:of|for)\s+([a-zA-Z0-9\s_-]+?)(?:[.,:;]|\s+reveals|\s+shows|\s+indicates|\s+identified)/i)
      if (matchFor && matchFor[1].trim().length > 3 && matchFor[1].trim().length < 40) {
        return shorten(cleanTitle(matchFor[1]), 40)
      }
    }
  }

  // 2. If user attached a file, derive from clean file name
  if (fileName) {
    const base = fileName.replace(/\.[^/.]+$/, '').replace(/[-_]+/g, ' ').trim()
    if (base) {
      const formatted = base.split(' ').map(w => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase()).join(' ')
      return shorten(formatted, 38)
    }
  }

  // 3. If user supplied text prompt, strip filler prefixes
  if (userText && !isGreeting(userText)) {
    let clean = userText.trim().replace(/\s+/g, ' ')
    clean = clean.replace(/^(?:can you|please|kindly|could you|would you|i want to|i need to|help me|can u|plz)\s+/i, '')
    clean = clean.replace(/^(?:audit|review|check|inspect|analyze|look at|examine|evaluate)\s+(?:this|the|my|our)?\s*/i, '')
    clean = clean.replace(/^(?:document|content|draft|text|copy|file|policy|spec|article)\s+(?:for|on|about|regarding)?\s*/i, '')
    clean = clean.replace(/^[?:!.,-\s]+/, '')
    if (clean.length > 2) {
      const capitalized = clean.charAt(0).toUpperCase() + clean.slice(1)
      return shorten(capitalized, 38)
    }
  }

  return 'New conversation'
}

function formatTimestamp(ts) {
  if (!ts) return 'TODAY'
  const d = new Date(ts)
  if (isNaN(d.getTime())) return String(ts)
  const now = new Date()
  const diffDays = Math.floor((now - d) / 86400000)
  if (diffDays === 0) {
    return `TODAY · ${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`
  } else if (diffDays === 1) {
    return 'YESTERDAY'
  } else {
    return d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short' }).toUpperCase()
  }
}

function getPreview(messages) {
  if (!messages || messages.length === 0) return 'Previous audit review.'
  const lastAi = [...messages].reverse().find(m => m.role === 'ai')
  if (lastAi?.data?.publish_readiness?.summary) {
    return lastAi.data.publish_readiness.summary.slice(0, 85) + (lastAi.data.publish_readiness.summary.length > 85 ? '...' : '')
  }
  const docMsg = messages.find(m => m.file?.name)
  if (docMsg?.file?.name) {
    return `Attached document: ${docMsg.file.name}`
  }
  const userMsg = messages.find(m => m.role === 'user' && m.content && !isGreeting(m.content))
  if (userMsg?.content) {
    return userMsg.content.slice(0, 85) + (userMsg.content.length > 85 ? '...' : '')
  }
  if (lastAi?.data?.message) {
    return lastAi.data.message.slice(0, 85)
  }
  return 'Audit consultation and consistency review.'
}

export default function App() {
  const [view, setView] = useState('home') // 'home' | 'chat'
  const [sessions, setSessions] = useState(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY)
      if (!saved) return []
      const list = JSON.parse(saved).filter(s => s.messages && s.messages.length > 0)
      // Upgrade any sessions with generic/uncleaned titles if not locked
      return list.map(s => {
        let t = s.title || 'New conversation'
        if (!s.titleLocked) {
          const firstUser = (s.messages || []).find(m => m.role === 'user')
          const firstAi = (s.messages || []).find(m => m.role === 'ai')
          const st = deriveSmartTitle(firstUser?.content, firstUser?.file?.name, firstAi?.data)
          if (st && st !== 'New conversation') {
            t = st
          } else if (isGreeting(t)) {
            t = 'New conversation'
          }
        }
        return { ...s, title: t }
      })
    } catch {
      return []
    }
  })

  const [currentSessionId, setCurrentSessionId] = useState(null)
  const [messages, setMessages] = useState([])
  const [title, setTitle] = useState('New conversation')
  const [editingTitle, setEditingTitle] = useState(false)
  const [titleDraft, setTitleDraft] = useState('')
  const [inputVal, setInputVal] = useState('')
  const [selectedFile, setSelectedFile] = useState(null)
  const [loading, setLoading] = useState(false)
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [activeViewerDoc, setActiveViewerDoc] = useState(null)

  const messagesEndRef = useRef(null)
  const fileInputRef = useRef(null)
  const homeFileInputRef = useRef(null)

  // Persist sessions to localStorage (NEVER save empty conversations)
  useEffect(() => {
    const valid = sessions.filter(s => s.messages && s.messages.length > 0)
    localStorage.setItem(STORAGE_KEY, JSON.stringify(valid))
  }, [sessions])

  // Scroll to last message / AI card
  const scrollToBottom = () => {
    setTimeout(() => {
      const container = document.querySelector('.messages')
      if (!container) return
      const aiCards = container.querySelectorAll('.bubble.ai')
      if (aiCards.length > 0) {
        aiCards[aiCards.length - 1].scrollIntoView({ behavior: 'smooth', block: 'start' })
      } else {
        container.scrollTop = container.scrollHeight
      }
    }, 100)
  }

  useEffect(() => {
    if (view === 'chat') {
      scrollToBottom()
    }
  }, [messages, view])

  function handleNewChat() {
    setCurrentSessionId(null)
    setMessages([])
    setTitle('New conversation')
    setEditingTitle(false)
    setTitleDraft('')
    setSelectedFile(null)
    setActiveViewerDoc(null)
    setView('chat')
  }

  function handleLoadSession(session) {
    setCurrentSessionId(session.id)
    setMessages(session.messages || [])
    setTitle(session.title || 'New conversation')
    setEditingTitle(false)
    setTitleDraft('')
    setSelectedFile(null)
    setActiveViewerDoc(null)
    setView('chat')
  }

  function handleRenameSession(id, newTitle) {
    const clean = newTitle.trim() || 'Untitled audit'
    setSessions(prev => prev.map(s => s.id === id ? { ...s, title: clean, titleLocked: true } : s))
    if (currentSessionId === id) {
      setTitle(clean)
    }
  }

  function commitTitle() {
    const clean = titleDraft.trim()
    if (clean && clean !== title) {
      setTitle(clean)
      if (currentSessionId) {
        handleRenameSession(currentSessionId, clean)
      }
    }
    setEditingTitle(false)
  }

  function handleDeleteSession(id) {
    setSessions(prev => prev.filter(s => s.id !== id))
    if (currentSessionId === id) {
      handleNewChat()
    }
  }

  function openDocument(msg) {
    const meta = msg?.docMeta || msg?.file?.meta || (messages.find(m => m.docMeta)?.docMeta) || {}
    const docObj = {
      name: msg?.file?.name || meta.filename || 'Document',
      viewUrl: meta.view_url
        ? (meta.view_url.startsWith('http') ? meta.view_url : `${import.meta.env.VITE_API_BASE || ''}${meta.view_url}`)
        : (msg?.file?.localBlobUrl || null),
      downloadUrl: meta.url
        ? (meta.url.startsWith('http') ? meta.url : `${import.meta.env.VITE_API_BASE || ''}${meta.url}`)
        : null,
      preview: meta.preview || '',
      rawMeta: meta
    }
    setActiveViewerDoc(docObj)
  }

  function handleStartFromHome(customTitle, initialText, file) {
    const newSessionId = 'lens_' + Date.now()
    setCurrentSessionId(newSessionId)
    setMessages([])
    const initialSmartTitle = deriveSmartTitle(initialText, file?.name, null)
    setTitle(initialSmartTitle)
    setView('chat')

    if (file || initialText) {
      executeSend(initialText, file, newSessionId, [], initialSmartTitle)
    }
  }

  async function executeSend(textToSend, fileToSend, targetSessionId, baseMessages = null, initialTitle = null) {
    const cleanText = (textToSend || '').trim()
    if (!cleanText && !fileToSend) return

    const currentList = baseMessages !== null ? baseMessages : messages
    const localUrl = fileToSend ? URL.createObjectURL(fileToSend) : null
    const userMsg = {
      id: 'usr_' + Date.now(),
      role: 'user',
      content: cleanText,
      file: fileToSend ? {
        name: fileToSend.name,
        size: (fileToSend.size / 1024).toFixed(1) + ' KB',
        localBlobUrl: localUrl
      } : null
    }

    const nextMessages = [...currentList, userMsg]
    setMessages(nextMessages)
    setInputVal('')
    setSelectedFile(null)
    setLoading(true)

    // Check if session title is already custom-locked by the user
    const sid = targetSessionId || currentSessionId || ('lens_' + Date.now())
    const existingSession = sessions.find(s => s.id === sid)
    const isLocked = existingSession?.titleLocked || false

    let sessionTitle = title
    if (!isLocked && (sessionTitle === 'New conversation' || sessionTitle === 'Conversation' || isGreeting(sessionTitle))) {
      sessionTitle = initialTitle || deriveSmartTitle(cleanText, fileToSend?.name, null)
      setTitle(sessionTitle)
    }

    try {
      const conversationHistory = nextMessages.map(m => ({
        role: m.role,
        content: m.role === 'user' ? m.content : (m.data?.publish_readiness ? m.data.publish_readiness.summary : (m.content || ''))
      }))

      const response = await reviewContent({
        file: fileToSend,
        text: cleanText,
        conversationHistory
      })

      if (response.document_metadata && userMsg.file) {
        userMsg.docMeta = response.document_metadata
      }

      const aiMsg = {
        id: 'ai_' + Date.now(),
        role: 'ai',
        data: response,
        docMeta: response.document_metadata || null
      }

      const finalMessages = [...nextMessages, aiMsg]
      setMessages(finalMessages)

      // Enhance title with AI findings if not locked by user
      if (!isLocked) {
        const enhancedTitle = deriveSmartTitle(cleanText, fileToSend?.name, response)
        if (enhancedTitle && enhancedTitle !== 'New conversation') {
          sessionTitle = enhancedTitle
          setTitle(sessionTitle)
        }
      }

      if (!currentSessionId) setCurrentSessionId(sid)

      setSessions(prev => {
        const existing = prev.find(s => s.id === sid)
        if (existing) {
          return prev.map(s => s.id === sid ? {
            ...s,
            title: isLocked ? s.title : sessionTitle,
            titleLocked: isLocked,
            messages: finalMessages,
            updatedAt: Date.now()
          } : s)
        } else {
          return [{
            id: sid,
            title: sessionTitle,
            titleLocked: false,
            messages: finalMessages,
            updatedAt: Date.now()
          }, ...prev]
        }
      })
    } catch (err) {
      const errMsg = {
        id: 'err_' + Date.now(),
        role: 'ai',
        data: {
          type: 'chat',
          message: `LENS encountered a processing error: ${err.message || 'Please retry.'}`
        }
      }
      setMessages([...nextMessages, errMsg])
    } finally {
      setLoading(false)
    }
  }

  function handleSubmit(e) {
    e.preventDefault()
    if (loading) return
    executeSend(inputVal, selectedFile)
  }

  return (
    <div className="app">
      <div className="aurora" />

      {/* HOME VIEW */}
      {view === 'home' && (
        <section id="home">
          <header>
            <div className="word">LENS</div>
            <button className="enter" onClick={() => handleNewChat()} type="button">
              ENTER WORKSPACE ↗
            </button>
          </header>

          <main className="home">
            <div className="eyebrow">CONTENT REVIEWER & CONSISTENCY AUDITOR</div>
            <h1>
              Look closer.<br />
              <span>Publish stronger.</span>
            </h1>
            <p className="sub">
              A focused AI audit space for contracts, policies, specifications, and articles. Auditing clarity, completeness, and consistency before you publish.
            </p>

            <div className="promptGlow">
              <div className="prompt">
                <input
                  type="file"
                  className="fileInput"
                  ref={homeFileInputRef}
                  onChange={e => {
                    const f = e.target.files?.[0]
                    if (f) setSelectedFile(f)
                  }}
                />
                <button
                  className="startAttach"
                  type="button"
                  title="Attach document to review"
                  onClick={() => homeFileInputRef.current?.click()}
                >
                  <svg className="icon" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8">
                    <path d="m21.4 11.6-8.9 8.9a6 6 0 0 1-8.5-8.5l9.3-9.3a4 4 0 0 1 5.7 5.7l-9.3 9.3a2 2 0 0 1-2.8-2.8l8.6-8.6" />
                  </svg>
                </button>
                <input
                  placeholder="Ask LENS to review, or attach a document..."
                  value={inputVal}
                  onChange={e => setInputVal(e.target.value)}
                  onKeyDown={e => {
                    if (e.key === 'Enter') {
                      e.preventDefault()
                      handleStartFromHome(null, inputVal, selectedFile)
                    }
                  }}
                />
                <button
                  className="send"
                  type="button"
                  onClick={() => handleStartFromHome(null, inputVal, selectedFile)}
                >
                  <svg className="icon" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M5 12h13" />
                    <path d="m13 7 5 5-5 5" />
                  </svg>
                </button>
              </div>
            </div>

            {selectedFile && (
              <div className="filePill">
                <span>Attached: {selectedFile.name} ({(selectedFile.size / 1024).toFixed(1)} KB)</span>
                <button onClick={() => setSelectedFile(null)}>✕</button>
              </div>
            )}

            <div className="recentGroup">
              <div className="recentOnly">
                <span>RECENT CONVERSATIONS</span>
              </div>

              <div className="cards">
                {sessions.length > 0 ? (
                  sessions.slice(0, 3).map(s => (
                    <button
                      key={s.id}
                      className="card"
                      type="button"
                      onClick={() => handleLoadSession(s)}
                    >
                      <small>{formatTimestamp(s.updatedAt || s.timestamp)}</small>
                      <b>{s.title}</b>
                      <p>{getPreview(s.messages)}</p>
                    </button>
                  ))
                ) : (
                  <div className="card emptyCard">
                    <small>NOTHING YET</small>
                    <b>No audits yet</b>
                    <p>Message LENS or attach a document above to begin.</p>
                  </div>
                )}
              </div>
            </div>
          </main>
        </section>
      )}

      {/* CHAT VIEW */}
      {view === 'chat' && (
        <section className="chatPage">
          <div className={`layout${activeViewerDoc ? ' withViewer' : ''}`}>
            {/* Sidebar */}
            <LensSidebar
              sessions={sessions}
              currentSessionId={currentSessionId}
              onNew={handleNewChat}
              onLoad={handleLoadSession}
              onClose={() => setSidebarOpen(false)}
              isOpen={sidebarOpen}
              onRename={handleRenameSession}
              onDelete={handleDeleteSession}
            />

            {/* Main Chat Area */}
            <main className="chat">
              {/* Header: Clickable inline editable title */}
              <div className="chatHead">
                <div>
                  {editingTitle ? (
                    <input
                      autoComplete="off"
                      autoFocus
                      className="titleInput"
                      value={titleDraft}
                      maxLength={60}
                      onChange={e => setTitleDraft(e.target.value)}
                      onBlur={commitTitle}
                      onKeyDown={e => {
                        if (e.key === 'Enter') commitTitle()
                        if (e.key === 'Escape') setEditingTitle(false)
                      }}
                    />
                  ) : (
                    <b
                      id="title"
                      className="titleEditable"
                      title="Click to rename"
                      onClick={() => {
                        setTitleDraft(title)
                        setEditingTitle(true)
                      }}
                    >
                      {title || 'New conversation'}
                    </b>
                  )}
                  <small>CONTENT AUDIT WORKSPACE</small>
                </div>
                <div className="mobileActions">
                  <button
                    className="mobileMenu"
                    type="button"
                    onClick={() => setSidebarOpen(!sidebarOpen)}
                  >
                    <span>AUDITS</span>
                  </button>
                  <button
                    className="ghost"
                    type="button"
                    onClick={() => setView('home')}
                  >
                    <svg className="icon" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="m3 10 9-7 9 7" />
                      <path d="M5 9v11h14V9" />
                      <path d="M9 20v-6h6v6" />
                    </svg>
                    <span style={{ marginLeft: 6 }}>HOME</span>
                  </button>
                </div>
              </div>

              {/* Messages Container */}
              <div className="messages">
                {messages.length === 0 && (
                  <div style={{ textAlign: 'center', color: 'var(--muted)', marginTop: 40, fontSize: 14 }}>
                    Send a message or attach a document to start your audit with LENS.
                  </div>
                )}

                {messages.map(msg => {
                  if (msg.role === 'user') {
                    return (
                      <div key={msg.id} className="bubble user">
                        {msg.file && (
                          <button
                            type="button"
                            className="userFileCard"
                            onClick={() => openDocument(msg)}
                            title="Open document"
                          >
                            <div className="userFileHeader">
                              <div className="userFileLeft">
                                <span className="userFileIcon">📄</span>
                                <div className="userFileInfo">
                                  <span className="userFileName">{msg.file.name}</span>
                                  <span className="userFileMeta">{msg.file.size}</span>
                                </div>
                              </div>
                              <span className="userFileViewBtn">Open ↗</span>
                            </div>
                          </button>
                        )}
                        {msg.content && <p>{msg.content}</p>}
                      </div>
                    )
                  }

                  // AI Answer Card (NO duplicate open button here)
                  return (
                    <div key={msg.id} className="bubble ai">
                      <LensResultCard data={msg.data} />
                    </div>
                  )
                })}

                {loading && (
                  <div className="thinking">
                    <span className="thinkName">LENS</span>
                    <span className="bars">
                      <i /><i /><i /><i />
                    </span>
                  </div>
                )}
                <div ref={messagesEndRef} />
              </div>

              {/* Composer */}
              <div className="composerArea">
                <div className="composer">
                  <form onSubmit={handleSubmit}>
                    <input
                      type="file"
                      className="fileInput"
                      ref={fileInputRef}
                      onChange={e => {
                        const f = e.target.files?.[0]
                        if (f) setSelectedFile(f)
                      }}
                    />
                    <button
                      className="plus"
                      type="button"
                      title="Attach document to review"
                      onClick={() => fileInputRef.current?.click()}
                    >
                      <svg className="icon" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8">
                        <path d="m21.4 11.6-8.9 8.9a6 6 0 0 1-8.5-8.5l9.3-9.3a4 4 0 0 1 5.7 5.7l-9.3 9.3a2 2 0 0 1-2.8-2.8l8.6-8.6" />
                      </svg>
                    </button>
                    <input
                      placeholder={selectedFile ? `Attached: ${selectedFile.name} — Add review focus...` : "Message LENS or paste draft to audit..."}
                      value={inputVal}
                      onChange={e => setInputVal(e.target.value)}
                      disabled={loading}
                    />
                    <button className="chatSend" type="submit" disabled={loading}>
                      <svg className="icon" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2">
                        <path d="M5 12h13" />
                        <path d="m13 7 5 5-5 5" />
                      </svg>
                    </button>
                  </form>
                </div>
                {selectedFile && (
                  <div className="filePill" style={{ maxWidth: 840, marginTop: 8 }}>
                    <span>Attached: {selectedFile.name} ({(selectedFile.size / 1024).toFixed(1)} KB)</span>
                    <button onClick={() => setSelectedFile(null)}>✕</button>
                  </div>
                )}
                <div className="fine">
                  ENTERPRISE BFSI · CONTENT AUDITOR · ZERO HALLUCINATIONS · SECURE & SANITIZED
                </div>
              </div>
            </main>

            {/* Document Viewer Side-Panel */}
            {activeViewerDoc && (
              <DocumentViewer
                doc={activeViewerDoc}
                onClose={() => setActiveViewerDoc(null)}
              />
            )}
          </div>
        </section>
      )}
    </div>
  )
}
