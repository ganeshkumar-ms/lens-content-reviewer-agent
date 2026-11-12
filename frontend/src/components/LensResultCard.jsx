import { useState } from 'react'

export default function LensResultCard({ data }) {
  const [copiedId, setCopiedId] = useState(null)

  if (!data) return null

  // Fallback to simple chat message if not a structured review
  if (data.type === 'chat' || (!data.publish_readiness && data.message)) {
    return (
      <div className="lensChatReply">
        <p>{data.message}</p>
      </div>
    )
  }

  const pr = data.publish_readiness || {}
  const metrics = data.metrics || {}
  const rawIssues = Array.isArray(data.issues) ? data.issues : []
  const issues = rawIssues.map((issue, idx) => {
    if (typeof issue === 'string') {
      return {
        id: `ISSUE-${idx + 1}`,
        severity: 'WARNING',
        category: 'CONSISTENCY',
        location: 'Document Content',
        excerpt: '',
        issue: issue,
        why_it_matters: 'May create confusion or conflicting expectations for the reader.',
        suggested_fix: ''
      }
    }
    return issue || {}
  })
  const strengths = Array.isArray(data.strengths) ? data.strengths : []
  const recs = Array.isArray(data.recommendations) ? data.recommendations : []

  const score = typeof pr.score === 'number' ? pr.score : 75
  const status = pr.status || (score >= 85 ? 'READY_TO_PUBLISH' : score < 50 ? 'CRITICAL_BLOCKERS' : 'NEEDS_REVISION')

  const statusConfig = {
    READY_TO_PUBLISH: {
      label: 'READY TO PUBLISH',
      icon: '✓',
      badgeClass: 'statusReady',
      color: '#08d6a2'
    },
    NEEDS_REVISION: {
      label: 'NEEDS REVISION',
      icon: '⚠',
      badgeClass: 'statusWarn',
      color: '#ffb347'
    },
    CRITICAL_BLOCKERS: {
      label: 'CRITICAL BLOCKERS',
      icon: '⛔',
      badgeClass: 'statusDanger',
      color: '#ff5c5c'
    }
  }[status] || {
    label: 'UNDER REVIEW',
    icon: 'ℹ',
    badgeClass: 'statusWarn',
    color: '#08d6a2'
  }

  function handleCopyFix(id, text) {
    if (!text) return
    navigator.clipboard.writeText(text).then(() => {
      setCopiedId(id)
      setTimeout(() => setCopiedId(null), 2000)
    })
  }

  return (
    <div className="lensResultCard">
      {/* Header: Publish Readiness & Score */}
      <div className="lensScoreHeader">
        <div className="lensScoreBadgeWrap">
          <span className={`lensStatusBadge ${statusConfig.badgeClass}`}>
            <span className="badgeDot" />
            {statusConfig.icon} {statusConfig.label}
          </span>
          <div className="lensScoreNumberWrap">
            <span className="lensScoreNumber" style={{ color: statusConfig.color }}>{score}</span>
            <span className="lensScoreMax">/ 100</span>
          </div>
        </div>

        <div className="lensScoreBarBg">
          <div
            className="lensScoreBarFill"
            style={{
              width: `${Math.min(100, Math.max(0, score))}%`,
              backgroundColor: statusConfig.color
            }}
          />
        </div>

        {pr.summary && (
          <p className="lensSummaryText">{pr.summary}</p>
        )}
      </div>

      {/* Sleek Findings Ribbon (No bulky oversized boxes) */}
      <div className="lensMetricsStrip">
        <div className="lensMetricPill">
          <div className="lensMetricLeft">
            <span className="metricDot crit" />
            <span className="metricLabel">Critical</span>
          </div>
          <b className={`metricCount ${metrics.critical_issues_count > 0 ? 'crit' : 'zero'}`}>
            {metrics.critical_issues_count || 0}
          </b>
        </div>

        <div className="lensMetricPill">
          <div className="lensMetricLeft">
            <span className="metricDot warn" />
            <span className="metricLabel">Warnings</span>
          </div>
          <b className={`metricCount ${metrics.warnings_count > 0 ? 'warn' : 'zero'}`}>
            {metrics.warnings_count || 0}
          </b>
        </div>

        <div className="lensMetricPill">
          <div className="lensMetricLeft">
            <span className="metricDot sugg" />
            <span className="metricLabel">Suggestions</span>
          </div>
          <b className={`metricCount ${metrics.suggestions_count > 0 ? 'sugg' : 'zero'}`}>
            {metrics.suggestions_count || 0}
          </b>
        </div>

        {metrics.consistency_rating && (
          <div className="lensMetricPill consistency">
            <div className="lensMetricLeft">
              <span className="metricDot cons" />
              <span className="metricLabel">Consistency</span>
            </div>
            <b className="metricText">
              {metrics.consistency_rating.replace(/\s*·.*$/, '')}
            </b>
          </div>
        )}
      </div>

      {/* Actionable Review Matrix */}
      {issues.length > 0 && (
        <div className="lensSection">
          <div className="lensSectionHead">
            <b>ACTIONABLE REVIEW MATRIX</b>
            <span>{issues.length} {issues.length === 1 ? 'FINDING' : 'FINDINGS'} DETECTED</span>
          </div>

          <div className="lensIssuesList">
            {issues.map((issue, idx) => {
              const sev = (issue.severity || 'WARNING').toUpperCase()
              const isCopied = copiedId === (issue.id || idx)

              return (
                <div key={issue.id || idx} className={`lensIssueCard sev-${sev.toLowerCase()}`}>
                  <div className="lensIssueHead">
                    <span className={`lensSevPill sev-${sev.toLowerCase()}`}>
                      {sev}
                    </span>
                    {issue.category && (
                      <span className="lensCatPill">{issue.category}</span>
                    )}
                    {issue.location && (
                      <span className="lensLocationPill">📍 {issue.location}</span>
                    )}
                  </div>

                  {issue.excerpt && (
                    <div className="lensExcerptBox">
                      <small>EXCERPT FROM CONTENT:</small>
                      <p>"{issue.excerpt}"</p>
                    </div>
                  )}

                  <div className="lensIssueBody">
                    <p className="lensIssueDesc">
                      <strong>Issue:</strong> {issue.issue}
                    </p>
                    {issue.why_it_matters && (
                      <p className="lensWhyMatters">
                        <strong>Why it matters:</strong> {issue.why_it_matters}
                      </p>
                    )}
                  </div>

                  {issue.suggested_fix && (
                    <div className="lensFixBox">
                      <div className="lensFixHead">
                        <span>SUGGESTED REPLACEMENT:</span>
                        <button
                          type="button"
                          className="lensCopyBtn"
                          onClick={() => handleCopyFix(issue.id || idx, issue.suggested_fix)}
                        >
                          {isCopied ? '✓ Copied' : 'Copy Fix 📋'}
                        </button>
                      </div>
                      <pre className="lensFixText">{issue.suggested_fix}</pre>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Strengths & Recommendations */}
      <div className="lensDualGrid">
        {strengths.length > 0 && (
          <div className="lensCardBox">
            <b className="lensCardBoxTitle">✓ Content Strengths</b>
            <ul className="lensList">
              {strengths.map((s, i) => (
                <li key={i}>{s}</li>
              ))}
            </ul>
          </div>
        )}

        {recs.length > 0 && (
          <div className="lensCardBox">
            <b className="lensCardBoxTitle">⚡ Pre-Publish Checklist</b>
            <ul className="lensList">
              {recs.map((r, i) => (
                <li key={i}>{r}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  )
}

