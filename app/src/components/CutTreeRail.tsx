import { useState } from 'react'
import type { Graph, GraphCommit, Status, Version } from '../types'

const LANE_COLORS = ['#F59E0B', '#34D399', '#60A5FA', '#A78BFA', '#FB7185']

type Props = {
  graph: Graph | null
  log: Version[]
  status: Status | null
  selected: Version | null
  activeTimeline: string | null
  onSelectVersion: (v: Version) => void
  onOpenNewBranch: () => void
  onSyncRemote: () => void
}

export default function CutTreeRail({
  graph,
  log,
  status,
  selected,
  activeTimeline,
  onSelectVersion,
  onOpenNewBranch,
  onSyncRemote,
}: Props) {
  const [showTech, setShowTech] = useState(false)

  const ROW = 64
  const LANE_STEP = 20
  const START_X = 18

  const commits: GraphCommit[] = graph?.commits?.length
    ? graph.commits
    : log.map((v, i) => ({
        hash: v.hash,
        short: v.short,
        message: v.message,
        date: v.date,
        lane: 0,
        branchName: status?.current_branch || 'main',
        isBranch: false,
        isFork: false,
        isCurrent: i === 0,
      }))

  const maxLane = commits.reduce((m, c) => Math.max(m, c.lane || 0), 0)
  const svgW = Math.max(48, START_X + (maxLane + 1) * LANE_STEP + 10)
  const svgH = Math.max(commits.length * ROW, 120)

  const coords = new Map<string, { x: number; y: number; color: string; lane: number }>()
  commits.forEach((c, idx) => {
    const lane = c.lane || 0
    coords.set(c.hash, {
      x: START_X + lane * LANE_STEP,
      y: idx * ROW + ROW / 2,
      color: LANE_COLORS[lane % LANE_COLORS.length],
      lane,
    })
  })

  const selectedCommit = commits.find(c => c.hash === selected?.hash)

  return (
    <aside className="gitRail">
      <div
        className="h"
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          padding: '12px 14px',
          margin: 0,
          borderBottom: '1px solid var(--border)',
        }}
      >
        <div>
          <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--text-secondary)' }}>
            Cut Tree
          </div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--muted2)', marginTop: 2 }}>
            {(graph?.branches || status?.branches || ['main']).length} cuts • {commits.length} saves
          </div>
        </div>
        <button type="button" className="ghost" style={{ padding: '4px 10px', fontSize: 11 }} onClick={onOpenNewBranch}>
          + New Cut
        </button>
      </div>

      <div className="gitRailScroll">
        <div style={{ position: 'relative', minHeight: svgH }}>
          <svg width={svgW} height={svgH} style={{ position: 'absolute', left: 0, top: 0, pointerEvents: 'none' }}>
            {commits.map((c) => {
              const cur = coords.get(c.hash)
              if (!cur) return null
              return (c.parents || []).map((ph) => {
                const par = coords.get(ph)
                if (!par) return null
                if (cur.x === par.x) {
                  return (
                    <line
                      key={`${c.hash}-${ph}`}
                      x1={cur.x}
                      y1={cur.y}
                      x2={par.x}
                      y2={par.y}
                      stroke={cur.color}
                      strokeWidth={1.75}
                      strokeOpacity={0.72}
                    />
                  )
                }
                const midY = (cur.y + par.y) / 2
                return (
                  <path
                    key={`${c.hash}-${ph}`}
                    d={`M ${cur.x} ${cur.y} C ${cur.x} ${midY}, ${par.x} ${midY}, ${par.x} ${par.y}`}
                    fill="none"
                    stroke={cur.color}
                    strokeWidth={1.75}
                    strokeOpacity={0.8}
                  />
                )
              })
            })}

            {commits.map((c) => {
              const pos = coords.get(c.hash)
              if (!pos) return null
              const isSel = selected?.hash === c.hash
              return (
                <g key={c.hash}>
                  {(isSel || c.isCurrent) && (
                    <circle cx={pos.x} cy={pos.y} r={9} fill={pos.color} fillOpacity={0.18} stroke={pos.color} strokeWidth={1.25} />
                  )}
                  <circle
                    cx={pos.x}
                    cy={pos.y}
                    r={isSel ? 4.2 : 3.5}
                    fill={isSel ? '#F4F4F5' : pos.color}
                    stroke="#131518"
                    strokeWidth={1.5}
                  />
                </g>
              )
            })}
          </svg>

          <div>
            {commits.map((c) => {
              const isSel = selected?.hash === c.hash
              const pos = coords.get(c.hash)
              const color = pos?.color || LANE_COLORS[0]
              const logMatch = log.find(v => v.hash === c.hash)

              return (
                <button
                  key={c.hash}
                  type="button"
                  className={`gitRowBtn ${isSel ? 'is-sel' : ''}`}
                  style={{ height: ROW, paddingLeft: svgW + 4 }}
                  onClick={() => {
                    if (logMatch) onSelectVersion(logMatch)
                  }}
                >
                  <div
                    style={{
                      fontSize: 12.5,
                      fontWeight: isSel || c.isCurrent ? 600 : 500,
                      color: isSel ? 'var(--text)' : 'var(--text-secondary)',
                      whiteSpace: 'nowrap',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      width: '100%',
                    }}
                  >
                    {c.message}
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 4, flexWrap: 'wrap' }}>
                    <span
                      style={{
                        fontFamily: 'var(--font-mono)',
                        fontSize: 9.5,
                        padding: '1px 5px',
                        borderRadius: 4,
                        background: `${color}22`,
                        color,
                      }}
                    >
                      {c.branchName || status?.current_branch || 'main'}
                    </span>
                    {c.isCurrent && (
                      <span
                        style={{
                          fontFamily: 'var(--font-mono)',
                          fontSize: 9.5,
                          padding: '1px 5px',
                          borderRadius: 4,
                          background: 'var(--green-soft)',
                          color: 'var(--green)',
                          border: '1px solid var(--green-border)',
                        }}
                      >
                        In Resolve
                      </span>
                    )}
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--muted2)' }}>
                      {c.relative || c.date}
                    </span>
                  </div>
                </button>
              )
            })}
            {commits.length === 0 && <div className="empty">No saves yet</div>}
          </div>
        </div>
      </div>

      <div className="gitRailFooter">
        <label style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 11, color: 'var(--text-secondary)', cursor: 'pointer' }}>
          <span>Technical Git / OTIO details</span>
          <input type="checkbox" checked={showTech} onChange={e => setShowTech(e.target.checked)} style={{ accentColor: 'var(--orange)' }} />
        </label>

        {showTech && selected && (
          <div className="techBox">
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span style={{ color: 'var(--muted2)' }}>Commit</span>
              <span style={{ color: 'var(--text)' }}>{selected.short}</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span style={{ color: 'var(--muted2)' }}>Parent</span>
              <span>{selectedCommit?.parents?.[0]?.slice(0, 8) || 'root'}</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span style={{ color: 'var(--muted2)' }}>File</span>
              <span style={{ color: 'var(--orange-strong)' }}>{selected.file || (activeTimeline ? `timelines/${activeTimeline}.otio` : 'timeline.otio')}</span>
            </div>
          </div>
        )}

        <div className="remoteCard">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: 11.5, fontWeight: 600, color: 'var(--text)' }}>GitHub Backup</span>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: status?.remote_url ? 'var(--green)' : 'var(--muted2)' }}>
              {status?.remote_url ? 'Connected' : 'Local only'}
            </span>
          </div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {status?.remote_url || 'No remote linked — saves stay local'}
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 2 }}>
            <span style={{ fontSize: 10, color: 'var(--muted2)' }}>Timelines only • Media local</span>
            <button type="button" className="ghost" style={{ padding: '4px 10px', fontSize: 11 }} onClick={onSyncRemote}>
              Push
            </button>
          </div>
        </div>
      </div>
    </aside>
  )
}
