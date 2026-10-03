import { useState, useEffect, useCallback } from 'react'
import {
  Github, Shield, Zap, Sparkles, TestTube,
  CheckCircle, XCircle, AlertCircle, Clock,
  Send, RefreshCw, ChevronDown, ChevronUp, ExternalLink,
  ArrowLeft, Activity, BarChart3, FileCode, GitPullRequest,
  AlertTriangle, Info, Loader2
} from 'lucide-react'

// ── Constants ─────────────────────────────────────────────────────
const API = ''  // proxied via vite

const AGENTS = [
  { key: 'security',    label: 'Security',    icon: Shield,   color: '#f78166', gradient: 'linear-gradient(135deg, #f78166 0%, #da3633 100%)' },
  { key: 'performance', label: 'Performance', icon: Zap,      color: '#f0883e', gradient: 'linear-gradient(135deg, #f0883e 0%, #d29922 100%)' },
  { key: 'style',       label: 'Style',       icon: Sparkles, color: '#bc8cff', gradient: 'linear-gradient(135deg, #bc8cff 0%, #8957e5 100%)' },
  { key: 'test',        label: 'Tests',       icon: TestTube, color: '#3fb950', gradient: 'linear-gradient(135deg, #3fb950 0%, #238636 100%)' },
]

const SEVERITY_CONFIG = {
  critical:   { color: '#f85149', bg: 'rgba(248, 81, 73, 0.08)', border: 'rgba(248, 81, 73, 0.2)', label: 'CRITICAL', icon: XCircle },
  warning:    { color: '#d29922', bg: 'rgba(210, 153, 34, 0.08)', border: 'rgba(210, 153, 34, 0.2)', label: 'WARNING',  icon: AlertTriangle },
  suggestion: { color: '#58a6ff', bg: 'rgba(88, 166, 255, 0.08)', border: 'rgba(88, 166, 255, 0.2)', label: 'SUGGEST',  icon: Info },
}

const VERDICT_CONFIG = {
  approve:         { color: '#3fb950', bg: 'rgba(63, 185, 80, 0.08)', icon: CheckCircle,  label: 'Approved',          description: 'All checks passed — this PR looks great!' },
  comment:         { color: '#d29922', bg: 'rgba(210, 153, 34, 0.08)', icon: AlertCircle,  label: 'Needs Discussion',  description: 'Some findings to review before merging.' },
  request_changes: { color: '#f85149', bg: 'rgba(248, 81, 73, 0.08)', icon: XCircle,      label: 'Changes Requested', description: 'Critical issues must be resolved.' },
}

// ── Animated Background ───────────────────────────────────────────
function AnimatedBackground() {
  return (
    <div style={{
      position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, zIndex: 0,
      overflow: 'hidden', pointerEvents: 'none',
    }}>
      {/* Top-right gradient orb */}
      <div style={{
        position: 'absolute', top: '-20%', right: '-10%',
        width: 600, height: 600, borderRadius: '50%',
        background: 'radial-gradient(circle, rgba(88, 166, 255, 0.06) 0%, transparent 70%)',
        animation: 'float 8s ease-in-out infinite',
      }} />
      {/* Bottom-left gradient orb */}
      <div style={{
        position: 'absolute', bottom: '-20%', left: '-10%',
        width: 500, height: 500, borderRadius: '50%',
        background: 'radial-gradient(circle, rgba(188, 140, 255, 0.05) 0%, transparent 70%)',
        animation: 'float 10s ease-in-out infinite 2s',
      }} />
      {/* Subtle grid pattern */}
      <div style={{
        position: 'absolute', inset: 0,
        backgroundImage: `
          linear-gradient(rgba(88, 166, 255, 0.02) 1px, transparent 1px),
          linear-gradient(90deg, rgba(88, 166, 255, 0.02) 1px, transparent 1px)
        `,
        backgroundSize: '60px 60px',
      }} />
    </div>
  )
}

// ── Status Badge ──────────────────────────────────────────────────
function StatusBadge({ status }) {
  const map = {
    pending:  { color: '#5d6d82', label: 'Pending',  bg: 'rgba(93, 109, 130, 0.12)' },
    queued:   { color: '#5d6d82', label: 'Queued',   bg: 'rgba(93, 109, 130, 0.12)' },
    fetching: { color: '#58a6ff', label: 'Fetching', bg: 'rgba(88, 166, 255, 0.12)' },
    running:  { color: '#f0883e', label: 'Running',  bg: 'rgba(240, 136, 62, 0.12)' },
    done:     { color: '#3fb950', label: 'Done',     bg: 'rgba(63, 185, 80, 0.12)' },
    error:    { color: '#f85149', label: 'Error',    bg: 'rgba(248, 81, 73, 0.12)' },
  }
  const cfg = map[status] || map.pending
  return (
    <span style={{
      background: cfg.bg, color: cfg.color,
      padding: '4px 12px', borderRadius: 99, fontSize: 11,
      fontWeight: 600, border: `1px solid ${cfg.color}22`,
      letterSpacing: '0.02em', textTransform: 'uppercase',
    }}>
      {status === 'running' && (
        <Loader2 size={10} style={{ marginRight: 4, verticalAlign: 'middle', animation: 'spin 1s linear infinite' }} />
      )}
      {cfg.label}
    </span>
  )
}

// ── Agent Card ────────────────────────────────────────────────────
function AgentCard({ agent, count, status }) {
  const Icon    = agent.icon
  const running = status === 'running'
  const done    = status === 'done'
  const err     = status === 'error'
  const hasFindings = done && count > 0

  return (
    <div style={{
      background: 'var(--bg-card)',
      border: `1px solid ${done ? (hasFindings ? agent.color + '44' : 'rgba(63, 185, 80, 0.3)') : 'var(--border-subtle)'}`,
      borderRadius: 14, padding: '18px 22px',
      display: 'flex', alignItems: 'center', gap: 14,
      transition: 'all 0.3s cubic-bezier(0.4, 0, 0.2, 1)',
      animation: done ? 'fadeIn 0.4s ease' : 'none',
      position: 'relative', overflow: 'hidden',
    }}>
      {/* Shimmer effect when running */}
      {running && (
        <div style={{
          position: 'absolute', inset: 0,
          background: `linear-gradient(90deg, transparent 0%, ${agent.color}08 50%, transparent 100%)`,
          backgroundSize: '200% 100%',
          animation: 'shimmer 2s linear infinite',
        }} />
      )}

      <div style={{
        width: 46, height: 46, borderRadius: 12,
        background: agent.color + '15',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        transition: 'all 0.3s', position: 'relative', flexShrink: 0,
        ...(running && { animation: 'pulse 1.5s ease-in-out infinite' }),
      }}>
        <Icon size={22} color={agent.color} />
      </div>
      <div style={{ flex: 1, position: 'relative', zIndex: 1 }}>
        <div style={{ fontWeight: 600, fontSize: 14, letterSpacing: '-0.01em' }}>
          {agent.label}
        </div>
        <div style={{ color: 'var(--text-secondary)', fontSize: 12, marginTop: 3 }}>
          {done
            ? `${count ?? 0} finding${count !== 1 ? 's' : ''}`
            : running ? 'Analysing…'
            : err ? 'Error occurred'
            : 'Waiting…'}
        </div>
      </div>
      <div style={{ position: 'relative', zIndex: 1 }}>
        {done && !hasFindings && (
          <div style={{
            width: 26, height: 26, borderRadius: '50%',
            background: 'rgba(63, 185, 80, 0.12)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            <CheckCircle size={15} color="#3fb950" />
          </div>
        )}
        {done && hasFindings && (
          <div style={{
            minWidth: 28, height: 28, borderRadius: 8,
            background: agent.color + '18',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 13, fontWeight: 700, color: agent.color,
            padding: '0 8px',
          }}>
            {count}
          </div>
        )}
        {err && (
          <div style={{
            width: 26, height: 26, borderRadius: '50%',
            background: 'rgba(248, 81, 73, 0.12)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            <XCircle size={15} color="#f85149" />
          </div>
        )}
        {running && (
          <Loader2 size={20} color={agent.color}
            style={{ animation: 'spin 1s linear infinite' }} />
        )}
      </div>
    </div>
  )
}

// ── Severity Stats Bar ────────────────────────────────────────────
function SeverityStats({ findings }) {
  const critical   = findings.filter(f => f.severity === 'critical').length
  const warning    = findings.filter(f => f.severity === 'warning').length
  const suggestion = findings.filter(f => f.severity === 'suggestion').length
  const total      = findings.length
  if (total === 0) return null

  return (
    <div style={{
      display: 'flex', gap: 16, padding: '14px 20px',
      background: 'var(--bg-card)', borderRadius: 12,
      border: '1px solid var(--border-subtle)',
      marginBottom: 20, animation: 'fadeIn 0.4s ease',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flex: 1 }}>
        <BarChart3 size={16} color="var(--text-secondary)" />
        <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-secondary)' }}>
          Severity Breakdown
        </span>
      </div>
      {critical > 0 && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <div style={{ width: 8, height: 8, borderRadius: '50%', background: '#f85149' }} />
          <span style={{ fontSize: 12, color: '#f85149', fontWeight: 600 }}>{critical} Critical</span>
        </div>
      )}
      {warning > 0 && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <div style={{ width: 8, height: 8, borderRadius: '50%', background: '#d29922' }} />
          <span style={{ fontSize: 12, color: '#d29922', fontWeight: 600 }}>{warning} Warning</span>
        </div>
      )}
      {suggestion > 0 && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <div style={{ width: 8, height: 8, borderRadius: '50%', background: '#58a6ff' }} />
          <span style={{ fontSize: 12, color: '#58a6ff', fontWeight: 600 }}>{suggestion} Suggestion</span>
        </div>
      )}
    </div>
  )
}

// ── Finding Card ──────────────────────────────────────────────────
function FindingCard({ finding, index }) {
  const [open, setOpen] = useState(false)
  const cfg = SEVERITY_CONFIG[finding.severity] || SEVERITY_CONFIG.suggestion
  const agentCfg = AGENTS.find(a => a.key === finding.agent)
  const SevIcon = cfg.icon

  return (
    <div style={{
      background: cfg.bg, border: `1px solid ${cfg.border}`,
      borderRadius: 12, marginBottom: 10, overflow: 'hidden',
      transition: 'all 0.2s cubic-bezier(0.4, 0, 0.2, 1)',
      animation: `fadeIn 0.3s ease ${index * 0.05}s both`,
    }}>
      <div
        onClick={() => setOpen(o => !o)}
        style={{
          padding: '14px 18px', cursor: 'pointer',
          display: 'flex', alignItems: 'center', gap: 10,
          transition: 'background 0.15s',
        }}
        onMouseEnter={e => e.currentTarget.style.background = 'rgba(255,255,255,0.02)'}
        onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
      >
        <SevIcon size={14} color={cfg.color} style={{ flexShrink: 0 }} />

        <span style={{
          background: cfg.color + '18', color: cfg.color,
          padding: '2px 8px', borderRadius: 6, fontSize: 10,
          fontWeight: 700, flexShrink: 0, letterSpacing: '0.05em',
        }}>{cfg.label}</span>

        {agentCfg && (
          <span style={{
            color: agentCfg.color, fontSize: 10,
            background: agentCfg.color + '12', padding: '2px 8px',
            borderRadius: 6, fontWeight: 600, flexShrink: 0,
          }}>
            {agentCfg.label}
          </span>
        )}

        <span style={{ flex: 1, fontWeight: 600, fontSize: 13, lineHeight: 1.3 }}>
          {finding.title}
        </span>
        <span style={{
          color: 'var(--text-muted)', fontSize: 11, flexShrink: 0,
          fontFamily: "'JetBrains Mono', monospace",
        }}>
          {finding.file?.split('/').pop()}
        </span>
        <div style={{
          transition: 'transform 0.2s',
          transform: open ? 'rotate(180deg)' : 'rotate(0deg)',
        }}>
          <ChevronDown size={14} color="var(--text-muted)" />
        </div>
      </div>

      {open && (
        <div style={{
          padding: '0 18px 18px',
          borderTop: '1px solid var(--border-subtle)',
          animation: 'fadeIn 0.2s ease',
        }}>
          <div style={{
            display: 'flex', gap: 8, margin: '14px 0 10px',
            fontSize: 11, color: 'var(--text-secondary)', flexWrap: 'wrap',
          }}>
            <code style={{
              background: 'var(--bg-primary)', padding: '3px 10px',
              borderRadius: 6, fontFamily: "'JetBrains Mono', monospace",
              fontSize: 11, border: '1px solid var(--border-subtle)',
            }}>
              <FileCode size={10} style={{ marginRight: 4, verticalAlign: 'middle' }} />
              {finding.file}
            </code>
            {finding.line_hint && (
              <code style={{
                background: 'var(--bg-primary)', padding: '3px 10px',
                borderRadius: 6, fontFamily: "'JetBrains Mono', monospace",
                fontSize: 11, border: '1px solid var(--border-subtle)',
              }}>
                {finding.line_hint}
              </code>
            )}
          </div>
          <p style={{
            fontSize: 13, color: 'var(--text-primary)', lineHeight: 1.7,
            marginBottom: 14, opacity: 0.9,
          }}>
            {finding.detail}
          </p>
          <div style={{
            background: 'var(--bg-primary)', borderRadius: 10, padding: '14px 16px',
            borderLeft: `3px solid ${cfg.color}`,
            border: '1px solid var(--border-subtle)',
            borderLeftColor: cfg.color, borderLeftWidth: 3,
          }}>
            <div style={{
              fontSize: 10, fontWeight: 700, color: cfg.color,
              marginBottom: 6, letterSpacing: '0.05em', textTransform: 'uppercase',
              display: 'flex', alignItems: 'center', gap: 6,
            }}>
              <Sparkles size={10} />
              SUGGESTION
            </div>
            <p style={{ fontSize: 13, color: 'var(--text-primary)', lineHeight: 1.7, opacity: 0.9 }}>
              {finding.suggestion}
            </p>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Progress Steps ────────────────────────────────────────────────
function ProgressIndicator({ status }) {
  const steps = [
    { key: 'queued',   label: 'Queued' },
    { key: 'fetching', label: 'Fetching PR' },
    { key: 'running',  label: 'Agents Running' },
    { key: 'done',     label: 'Complete' },
  ]
  const order = { queued: 0, fetching: 1, running: 2, done: 3, error: 3 }
  const current = order[status] ?? 0

  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 0,
      margin: '0 0 24px', padding: '16px 20px',
      background: 'var(--bg-card)', borderRadius: 12,
      border: '1px solid var(--border-subtle)',
    }}>
      {steps.map((step, i) => {
        const active  = i === current
        const done    = i < current
        const isError = status === 'error' && i === current
        return (
          <div key={step.key} style={{ display: 'flex', alignItems: 'center', flex: 1 }}>
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6 }}>
              <div style={{
                width: 28, height: 28, borderRadius: '50%',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                background: done ? 'rgba(63, 185, 80, 0.15)' : active ? 'rgba(88, 166, 255, 0.15)' : 'var(--bg-primary)',
                border: `2px solid ${done ? '#3fb950' : active ? '#58a6ff' : 'var(--border-subtle)'}`,
                transition: 'all 0.3s',
                ...(active && !isError && { animation: 'glow 2s ease-in-out infinite' }),
              }}>
                {done && <CheckCircle size={13} color="#3fb950" />}
                {active && !isError && (
                  <Loader2 size={13} color="#58a6ff" style={{ animation: 'spin 1s linear infinite' }} />
                )}
                {isError && <XCircle size={13} color="#f85149" />}
                {!done && !active && (
                  <div style={{
                    width: 6, height: 6, borderRadius: '50%',
                    background: 'var(--text-muted)',
                  }} />
                )}
              </div>
              <span style={{
                fontSize: 10, fontWeight: 600, letterSpacing: '0.02em',
                color: done ? '#3fb950' : active ? '#58a6ff' : 'var(--text-muted)',
              }}>
                {step.label}
              </span>
            </div>
            {i < steps.length - 1 && (
              <div style={{
                flex: 1, height: 2, margin: '0 8px',
                background: done ? '#3fb95040' : 'var(--border-subtle)',
                borderRadius: 1, transition: 'background 0.3s',
                marginBottom: 22,
              }} />
            )}
          </div>
        )
      })}
    </div>
  )
}

// ── Review Detail Panel ───────────────────────────────────────────
function ReviewDetail({ review, onBack }) {
  
  const [live, setLive] = useState(review)

    useEffect(() => {
    let ws
    let reconnectTimer
    let stopped = false

    const connect = () => {
      if (stopped) return

      const protocol =
        window.location.protocol === 'https:' ? 'wss:' : 'ws:'

      const wsUrl =
        `${protocol}//${window.location.host}/ws/review/${review.review_id}`

      ws = new WebSocket(wsUrl)

      ws.onopen = () => {
        console.log('Review WebSocket connected')
      }

      ws.onmessage = (event) => {
  try {
    const data = JSON.parse(event.data)

    if (data.type === 'ping') return

    if (data.review) {
      setLive(prev => {
        const next = {
          ...prev,
          ...data.review,
        }

        if (next.status === 'done' || next.status === 'error') {
          stopped = true
        }

        return next
      })
    }
  } catch (err) {
    console.error('Invalid WebSocket message:', err)
  }
}

      ws.onerror = (error) => {
        console.warn('Review WebSocket error:', error)
      }

      ws.onclose = () => {
  console.warn('Review WebSocket closed')

  if (!stopped) {
    reconnectTimer = setTimeout(() => {
      connect()
    }, 2000)
  }
}
    }

    connect()

    return () => {
      stopped = true
      clearTimeout(reconnectTimer)

      if (ws) {
        ws.close()
      }
    }
  }, [review.review_id])

  // Build allFindings from the stored serialized findings (BUG 1 fix)
  const allFindings = [
    ...(live.security_findings    || []),
    ...(live.performance_findings || []),
    ...(live.style_findings       || []),
    ...(live.test_findings        || []),
  ].sort((a, b) => {
    const order = { critical: 0, warning: 1, suggestion: 2 }
    return (order[a.severity] ?? 9) - (order[b.severity] ?? 9)
  })

  // Use allFindings.length, or fallback to backend count (BUG 7 fix)
  const totalFindings = allFindings.length || live.findings_count || 0

  // A finished pipeline with an agent in "error" is NOT a clean review.
  const failedAgents = AGENTS.filter(a => live[`${a.key}_status`] === 'error')

  const verdict = VERDICT_CONFIG[live.verdict] || VERDICT_CONFIG.comment
  const VerdictIcon = verdict.icon

  return (
    <div style={{ animation: 'slideUp 0.4s ease' }}>
      {/* Header */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 14, marginBottom: 24,
        flexWrap: 'wrap',
      }}>
        <button onClick={onBack} style={{
          background: 'var(--bg-card)', border: '1px solid var(--border-subtle)',
          color: 'var(--text-primary)', padding: '8px 16px', borderRadius: 10,
          cursor: 'pointer', fontSize: 13, fontWeight: 500,
          display: 'flex', alignItems: 'center', gap: 6,
          transition: 'all 0.2s', fontFamily: 'inherit',
        }}
          onMouseEnter={e => { e.currentTarget.style.background = 'var(--bg-card-hover)'; e.currentTarget.style.borderColor = 'var(--border-default)' }}
          onMouseLeave={e => { e.currentTarget.style.background = 'var(--bg-card)'; e.currentTarget.style.borderColor = 'var(--border-subtle)' }}
        >
          <ArrowLeft size={14} /> Back
        </button>
        <div style={{ flex: 1, minWidth: 200 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <GitPullRequest size={18} color="var(--accent-blue)" />
            <span style={{ fontSize: 18, fontWeight: 700, letterSpacing: '-0.02em' }}>
              PR #{live.pr_number}
            </span>
            <span style={{ color: 'var(--text-secondary)', fontSize: 15, fontWeight: 400 }}>
              — {live.pr_title || 'Loading…'}
            </span>
          </div>
          <div style={{ color: 'var(--text-muted)', fontSize: 13, marginTop: 4, display: 'flex', gap: 8, alignItems: 'center' }}>
            <span>{live.repo}</span>
            {live.pr_author && (
              <>
                <span style={{ color: 'var(--border-default)' }}>·</span>
                <span>@{live.pr_author}</span>
              </>
            )}
          </div>
        </div>
        <StatusBadge status={live.status} />
        {live.pr_url && (
          <a href={live.pr_url} target="_blank" rel="noreferrer"
            style={{
              color: 'var(--accent-blue)', display: 'flex', alignItems: 'center', gap: 5,
              fontSize: 13, textDecoration: 'none', fontWeight: 500,
              padding: '6px 14px', borderRadius: 8,
              background: 'rgba(88, 166, 255, 0.08)',
              border: '1px solid rgba(88, 166, 255, 0.15)',
              transition: 'all 0.2s',
            }}
            onMouseEnter={e => e.currentTarget.style.background = 'rgba(88, 166, 255, 0.15)'}
            onMouseLeave={e => e.currentTarget.style.background = 'rgba(88, 166, 255, 0.08)'}
          >
            View on GitHub <ExternalLink size={12} />
          </a>
        )}
      </div>

      {/* Progress indicator for in-progress reviews */}
      {live.status !== 'done' && live.status !== 'error' && (
        <ProgressIndicator status={live.status} />
      )}

      {/* Verdict banner */}
      {live.status === 'done' && (
        <div style={{
          background: verdict.bg,
          border: `1px solid ${verdict.color}25`,
          borderRadius: 14, padding: '18px 24px', marginBottom: 20,
          display: 'flex', alignItems: 'center', gap: 14,
          animation: 'fadeIn 0.4s ease',
        }}>
          <div style={{
            width: 42, height: 42, borderRadius: '50%',
            background: verdict.color + '18',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            flexShrink: 0,
          }}>
            <VerdictIcon size={22} color={verdict.color} />
          </div>
          <div style={{ flex: 1 }}>
            <span style={{ fontWeight: 700, color: verdict.color, fontSize: 17, letterSpacing: '-0.01em' }}>
              {verdict.label}
            </span>
            <div style={{ color: 'var(--text-secondary)', fontSize: 13, marginTop: 2 }}>
              {totalFindings} total findings posted to GitHub
            </div>
          </div>
          {live.completed_at && (
  <div
    style={{
      color: 'var(--text-muted)',
      fontSize: 11,
      textAlign: 'right',
    }}
  >
    <div>Completed</div>

    <div style={{ fontFamily: "'JetBrains Mono', monospace" }}>
      {new Date(
        live.completed_at.endsWith('Z')
          ? live.completed_at
          : live.completed_at + 'Z'
      ).toLocaleTimeString()}
    </div>
  </div>
)}
        </div>
      )}

      {/* Agent status grid */}
      <div style={{
        display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)',
        gap: 12, marginBottom: 24,
      }}>
        {AGENTS.map(agent => (
          <AgentCard
            key={agent.key}
            agent={agent}
            count={live[`${agent.key}_count`]}
            status={
              // Read this agent's OWN status field first — a global
              // pipeline error (e.g. GitHub post failed) must not paint
              // every agent card red if that agent actually succeeded.
              live[`${agent.key}_status`] ||
              (live.status === 'done'    ? 'done'    :
               live.status === 'running' ? 'running' :
               live.status === 'error'   ? 'error'   : 'pending')
            }
          />
        ))}
      </div>

      {/* Severity breakdown */}
      {allFindings.length > 0 && <SeverityStats findings={allFindings} />}

      {/* Findings */}
      {allFindings.length > 0 && (
        <div style={{ animation: 'slideUp 0.4s ease 0.2s both' }}>
          <div style={{
            display: 'flex', alignItems: 'center', gap: 10,
            marginBottom: 16,
          }}>
            <Activity size={16} color="var(--text-secondary)" />
            <h3 style={{ fontSize: 15, fontWeight: 700, letterSpacing: '-0.01em' }}>
              All Findings
            </h3>
            <span style={{
              background: 'var(--accent-blue)18', color: 'var(--accent-blue)',
              padding: '2px 10px', borderRadius: 99, fontSize: 12, fontWeight: 700,
            }}>
              {allFindings.length}
            </span>
          </div>
          {allFindings.map((f, i) => <FindingCard key={i} finding={f} index={i} />)}
        </div>
      )}

      {/* Incomplete review — some agents failed, so "clean" would be misleading */}
      {live.status === 'done' && totalFindings === 0 && failedAgents.length > 0 && (
        <div style={{
          textAlign: 'center', padding: '40px 20px',
          animation: 'fadeIn 0.5s ease',
        }}>
          <div style={{ fontSize: 18, fontWeight: 700, color: '#d29922', marginBottom: 6 }}>
            No findings, but the review is incomplete
          </div>
          <div style={{ color: 'var(--text-secondary)', fontSize: 14 }}>
            {failedAgents.map(a => a.label || a.key).join(', ')} did not run. Re-run the review before trusting this result.
          </div>
        </div>
      )}

      {/* No issues — only show when truly zero findings AND every agent completed */}
      {live.status === 'done' && totalFindings === 0 && failedAgents.length === 0 && (
        <div style={{
          textAlign: 'center', padding: '50px 20px',
          animation: 'fadeIn 0.5s ease',
        }}>
          <div style={{
            width: 72, height: 72, borderRadius: '50%',
            background: 'rgba(63, 185, 80, 0.1)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            margin: '0 auto 16px',
            animation: 'float 3s ease-in-out infinite',
          }}>
            <CheckCircle size={36} color="#3fb950" />
          </div>
          <div style={{ fontSize: 20, fontWeight: 700, color: '#3fb950', marginBottom: 6 }}>
            All Clear!
          </div>
          <div style={{ color: 'var(--text-secondary)', fontSize: 14 }}>
            The PR looks clean across all agents. Great work! 🎉
          </div>
        </div>
      )}

      {/* Errors section */}
      {live.errors?.length > 0 && (
        <div style={{
          marginTop: 20,
          background: 'rgba(248, 81, 73, 0.06)',
          border: '1px solid rgba(248, 81, 73, 0.2)',
          borderRadius: 12, padding: 18,
          animation: 'fadeIn 0.3s ease',
        }}>
          <div style={{
            color: '#f85149', fontWeight: 700, marginBottom: 10,
            display: 'flex', alignItems: 'center', gap: 8, fontSize: 14,
          }}>
            <AlertTriangle size={16} />
            Errors
          </div>
          {live.errors.map((e, i) => (
            <div key={i} style={{
              color: 'var(--text-primary)', fontSize: 12,
              fontFamily: "'JetBrains Mono', monospace",
              padding: '6px 0', borderTop: i > 0 ? '1px solid rgba(248, 81, 73, 0.1)' : 'none',
              opacity: 0.85,
            }}>{e}</div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Review List Row ───────────────────────────────────────────────
function ReviewRow({ review, onClick }) {
  const verdictCfg = VERDICT_CONFIG[review.verdict]

  return (
    <div
      onClick={onClick}
      style={{
        background: 'var(--bg-card)', border: '1px solid var(--border-subtle)',
        borderRadius: 12, padding: '16px 20px', cursor: 'pointer',
        display: 'flex', alignItems: 'center', gap: 14,
        transition: 'all 0.25s cubic-bezier(0.4, 0, 0.2, 1)',
      }}
      onMouseEnter={e => {
        e.currentTarget.style.borderColor = 'var(--border-default)'
        e.currentTarget.style.background = 'var(--bg-card-hover)'
        e.currentTarget.style.transform = 'translateY(-1px)'
      }}
      onMouseLeave={e => {
        e.currentTarget.style.borderColor = 'var(--border-subtle)'
        e.currentTarget.style.background = 'var(--bg-card)'
        e.currentTarget.style.transform = 'translateY(0)'
      }}
    >
      <div style={{
        width: 38, height: 38, borderRadius: 10,
        background: 'rgba(88, 166, 255, 0.08)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        flexShrink: 0,
      }}>
        <GitPullRequest size={18} color="var(--accent-blue)" />
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{
          fontWeight: 600, fontSize: 14, letterSpacing: '-0.01em',
          display: 'flex', alignItems: 'center', gap: 8,
        }}>
          <span>{review.repo}</span>
          <span style={{ color: 'var(--accent-blue)' }}>#{review.pr_number}</span>
        </div>
        <div style={{
          color: 'var(--text-muted)', fontSize: 12, marginTop: 3,
          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          display: 'flex', alignItems: 'center', gap: 6,
        }}>
          {review.pr_title || 'Fetching…'}
          {review.findings_count != null && review.findings_count > 0 && (
            <span style={{
              background: 'rgba(240, 136, 62, 0.12)', color: '#f0883e',
              padding: '1px 7px', borderRadius: 99, fontSize: 10, fontWeight: 600,
              flexShrink: 0,
            }}>
              {review.findings_count} findings
            </span>
          )}
        </div>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexShrink: 0 }}>
        {verdictCfg && (
          <div style={{
            width: 8, height: 8, borderRadius: '50%',
            background: verdictCfg.color,
          }} />
        )}
        <StatusBadge status={review.status} />
      </div>
      <div style={{
        color: 'var(--text-muted)', fontSize: 11,
        fontFamily: "'JetBrains Mono', monospace",
        flexShrink: 0,
      }}>
        {review.created_at?.slice(11, 16)} UTC
      </div>
    </div>
  )
}

// ── Main App ──────────────────────────────────────────────────────
export default function App() {
  const [reviews,   setReviews]   = useState([])
  const [selected,  setSelected]  = useState(null)
  const [prUrl,     setPrUrl]     = useState('')
  const [loading,   setLoading]   = useState(false)
  const [error,     setError]     = useState('')

  const fetchReviews = useCallback(async () => {
    try {
      const res  = await fetch(`${API}/api/reviews`)
      const data = await res.json()
      setReviews(data.reviews || [])
    } catch { /* ignore */ }
  }, [])

useEffect(() => {
    if (selected) return

    fetchReviews()

    const interval = setInterval(fetchReviews, 5000)

    return () => clearInterval(interval)
}, [selected, fetchReviews])

  const submitReview = async () => {
  if (!prUrl.trim()) return

  setLoading(true)
  setError('')

  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), 15000)

  try {
    const res = await fetch(`${API}/api/review`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-API-Key': import.meta.env.VITE_API_KEY || '',
      },
      body: JSON.stringify({ pr_url: prUrl.trim() }),
      signal: controller.signal,
    })

    const data = await res.json()

    if (!res.ok) {
      throw new Error(data.detail || 'Failed to start review')
    }

    setPrUrl('')

    await fetchReviews()

    setSelected({
      review_id: data.review_id,
      ...data,
    })

  } catch (e) {
    if (e.name === 'AbortError') {
      setError(
        'Request timed out while starting the review. The backend may still be processing it.'
      )
    } else {
      setError(e.message || 'Failed to start review')
    }
  } finally {
    clearTimeout(timeout)
    setLoading(false)
  }
}

  const handleSelectReview = async (review) => {
    try {
      const res  = await fetch(`${API}/api/review/${review.review_id}`)
      const data = await res.json()
      setSelected(data)
    } catch {
      setSelected(review)
    }
  }

  return (
    <div style={{
      maxWidth: 940, margin: '0 auto', padding: '40px 24px',
      position: 'relative', zIndex: 1,
    }}>
      <AnimatedBackground />

      {/* Header */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 16, marginBottom: 36,
        animation: 'fadeIn 0.5s ease',
      }}>
        <div style={{
          width: 52, height: 52,
          background: 'linear-gradient(135deg, rgba(88, 166, 255, 0.15) 0%, rgba(188, 140, 255, 0.15) 100%)',
          borderRadius: 14, display: 'flex', alignItems: 'center',
          justifyContent: 'center',
          border: '1px solid rgba(88, 166, 255, 0.2)',
          boxShadow: '0 0 30px rgba(88, 166, 255, 0.1)',
        }}>
          <Github size={28} color="#58a6ff" />
        </div>
        <div>
          <h1 style={{
            fontSize: 26, fontWeight: 800, letterSpacing: '-0.03em',
            background: 'linear-gradient(135deg, #e6edf3 0%, #8b99ad 100%)',
            WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent',
          }}>
            AI PR Reviewer
          </h1>
          <p style={{ color: 'var(--text-muted)', fontSize: 13, marginTop: 3, letterSpacing: '0.01em' }}>
            Security · Performance · Style · Test Coverage — powered by LangGraph + NVIDIA NIM
          </p>
        </div>
      </div>

      {selected ? (
        <ReviewDetail review={selected} onBack={() => setSelected(null)} />
      ) : (
        <>
          {/* Input */}
          <div style={{
            background: 'var(--glass-bg)', backdropFilter: 'var(--glass-blur)',
            WebkitBackdropFilter: 'var(--glass-blur)',
            border: '1px solid var(--glass-border)',
            borderRadius: 16, padding: 24, marginBottom: 32,
            animation: 'slideUp 0.4s ease 0.1s both',
          }}>
            <div style={{
              fontSize: 15, fontWeight: 600, marginBottom: 14,
              color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: 8,
            }}>
              <GitPullRequest size={16} color="var(--accent-blue)" />
              Review a Pull Request
            </div>
            <div style={{ display: 'flex', gap: 10 }}>
              <input
                value={prUrl}
                onChange={e => setPrUrl(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && submitReview()}
                placeholder="https://github.com/owner/repo/pull/42"
                style={{
                  flex: 1, background: 'var(--bg-primary)', border: '1px solid var(--border-subtle)',
                  borderRadius: 10, padding: '12px 16px', color: 'var(--text-primary)',
                  fontSize: 14, outline: 'none', fontFamily: 'inherit',
                  transition: 'border-color 0.2s',
                }}
                onFocus={e => e.target.style.borderColor = 'var(--accent-blue)'}
                onBlur={e => e.target.style.borderColor = 'var(--border-subtle)'}
              />
              <button
                onClick={submitReview}
                disabled={loading || !prUrl.trim()}
                style={{
                  background: loading ? 'var(--bg-elevated)' : 'linear-gradient(135deg, #238636 0%, #2ea043 100%)',
                  border: 'none', borderRadius: 10, padding: '12px 24px',
                  color: 'white', fontWeight: 600, fontSize: 14,
                  cursor: loading ? 'not-allowed' : 'pointer',
                  display: 'flex', alignItems: 'center', gap: 8,
                  opacity: !prUrl.trim() ? 0.4 : 1,
                  transition: 'all 0.2s', fontFamily: 'inherit',
                  boxShadow: loading ? 'none' : '0 2px 12px rgba(35, 134, 54, 0.3)',
                }}
              >
                {loading
                  ? <><Loader2 size={15} style={{ animation: 'spin 1s linear infinite' }} /> Starting…</>
                  : <><Send size={15} /> Review PR</>
                }
              </button>
            </div>
            {error && (
              <div style={{
                color: '#f85149', fontSize: 13, marginTop: 12,
                display: 'flex', alignItems: 'center', gap: 6,
                padding: '8px 12px', background: 'rgba(248, 81, 73, 0.06)',
                borderRadius: 8, border: '1px solid rgba(248, 81, 73, 0.15)',
              }}>
                <AlertTriangle size={13} />
                {error}
              </div>
            )}
            <div style={{
              color: 'var(--text-muted)', fontSize: 12, marginTop: 14,
              display: 'flex', alignItems: 'center', gap: 6,
            }}>
              <Info size={12} />
              Webhook also supported — add{' '}
              <code style={{
                color: 'var(--accent-blue)',
                fontFamily: "'JetBrains Mono', monospace",
                fontSize: 11, background: 'rgba(88, 166, 255, 0.08)',
                padding: '2px 6px', borderRadius: 4,
              }}>
                /webhook/github
              </code>{' '}
              to your repo settings
            </div>
          </div>

          {/* Recent Reviews */}
          <div style={{
            display: 'flex', justifyContent: 'space-between',
            alignItems: 'center', marginBottom: 16,
            animation: 'slideUp 0.4s ease 0.2s both',
          }}>
            <h2 style={{
              fontSize: 17, fontWeight: 700, letterSpacing: '-0.01em',
              display: 'flex', alignItems: 'center', gap: 8,
            }}>
              <Clock size={16} color="var(--text-secondary)" />
              Recent Reviews
            </h2>
            <button onClick={fetchReviews} style={{
              background: 'var(--bg-card)', border: '1px solid var(--border-subtle)',
              color: 'var(--text-secondary)', padding: '6px 14px', borderRadius: 8,
              cursor: 'pointer', fontSize: 12, display: 'flex',
              alignItems: 'center', gap: 6, fontFamily: 'inherit',
              fontWeight: 500, transition: 'all 0.2s',
            }}
              onMouseEnter={e => { e.currentTarget.style.borderColor = 'var(--border-default)'; e.currentTarget.style.color = 'var(--text-primary)' }}
              onMouseLeave={e => { e.currentTarget.style.borderColor = 'var(--border-subtle)'; e.currentTarget.style.color = 'var(--text-secondary)' }}
            >
              <RefreshCw size={12} /> Refresh
            </button>
          </div>

          {reviews.length === 0 ? (
            <div style={{
              textAlign: 'center', padding: '70px 20px',
              animation: 'fadeIn 0.5s ease',
            }}>
              <div style={{
                width: 72, height: 72, borderRadius: '50%',
                background: 'rgba(88, 166, 255, 0.06)',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                margin: '0 auto 16px',
              }}>
                <Github size={32} color="var(--text-muted)" style={{ opacity: 0.4 }} />
              </div>
              <div style={{ color: 'var(--text-secondary)', fontSize: 15, fontWeight: 500 }}>
                No reviews yet
              </div>
              <div style={{ color: 'var(--text-muted)', fontSize: 13, marginTop: 6 }}>
                Paste a PR URL above to get started
              </div>
            </div>
          ) : (
            <div style={{
              display: 'flex', flexDirection: 'column', gap: 10,
              animation: 'slideUp 0.4s ease 0.3s both',
            }}>
              {reviews.map(r => (
                <ReviewRow
                  key={r.review_id}
                  review={r}
                  onClick={() => handleSelectReview(r)}
                />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}
