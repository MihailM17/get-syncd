import { useEffect, useMemo, useRef, useState } from 'react'
import type { VisualClip, VisualTracksData } from '../types'

type Props = {
  data: VisualTracksData | null | undefined
  mode: 'overlay' | 'split'
  onModeChange: (m: 'overlay' | 'split') => void
  diffFilter: string
  activeChangeId: number | null
  playheadS: number
  onPlayheadChange: (s: number) => void
  onSelectClip: (changeId: number | null, startS: number) => void
}

function fmtTC(sec: number): string {
  const totalMs = Math.max(0, Math.round(sec * 1000))
  const h = Math.floor(totalMs / 3600000)
  const m = Math.floor((totalMs % 3600000) / 60000)
  const s = Math.floor((totalMs % 60000) / 1000)
  const ms = totalMs % 1000
  const p2 = (n: number) => String(n).padStart(2, '0')
  return `${p2(h)}:${p2(m)}:${p2(s)}.${String(ms).padStart(3, '0')}`
}

function fmtShortRuler(sec: number): string {
  const m = Math.floor(sec / 60)
  const s = Math.floor(sec % 60)
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

export default function TimelineDiffCanvas({
  data,
  mode,
  onModeChange,
  diffFilter,
  activeChangeId,
  playheadS,
  onPlayheadChange,
  onSelectClip,
}: Props) {
  const [zoom, setZoom] = useState(1)
  const [showGhosts, setShowGhosts] = useState(true)
  const [hoverClip, setHoverClip] = useState<{ clip: VisualClip; track: string; x: number; y: number } | null>(null)
  const [viewportW, setViewportW] = useState(640)
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const scrubbingRef = useRef(false)

  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    const ro = new ResizeObserver(entries => {
      for (const e of entries) setViewportW(Math.max(320, e.contentRect.width))
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const durationS = Math.max(data?.duration_s || 1, 1)
  const tracks = data?.tracks || []
  const innerW = Math.max(viewportW, Math.round(viewportW * zoom))
  const pxPerSec = innerW / durationS

  const ticks = useMemo(() => {
    const targetPx = 92
    const rawStep = targetPx / pxPerSec
    const niceSteps = [1, 2, 5, 10, 15, 30, 60, 120, 300]
    const step = niceSteps.find(s => s >= rawStep) || 600
    const out: number[] = []
    for (let t = 0; t <= durationS + 0.001; t += step) out.push(t)
    return out
  }, [durationS, pxPerSec])

  const updateScrubFromEvent = (clientX: number) => {
    const el = scrollRef.current
    if (!el) return
    const rect = el.getBoundingClientRect()
    const x = clientX - rect.left + el.scrollLeft
    onPlayheadChange(Math.max(0, Math.min(durationS, x / pxPerSec)))
  }

  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (scrubbingRef.current) updateScrubFromEvent(e.clientX)
    }
    const onUp = () => { scrubbingRef.current = false }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    return () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
  }, [pxPerSec, durationS])

  if (!data || tracks.length === 0) return null

  const matchesFilter = (status: string) => {
    if (diffFilter === 'all') return true
    if (diffFilter === 'modified') return status === 'modified' || status === 'reordered' || status === 'renamed'
    return status === diffFilter
  }

  const renderClip = (clip: VisualClip, trackName: string, isGhost = false) => {
    const left = clip.start_s * pxPerSec
    const width = Math.max(clip.duration_s * pxPerSec, 6)
    const isActive = activeChangeId !== null && clip.change_id === activeChangeId
    const isDimmed = !matchesFilter(clip.status)
    const hasHeadTrim = clip.status === 'trimmed' && Math.abs(clip.head_delta_s || 0) >= 0.01
    const hasTailTrim = clip.status === 'trimmed' && Math.abs(clip.tail_delta_s || 0) >= 0.01

    return (
      <div
        key={clip.id}
        className={`nle-clip st-${clip.status} ${isGhost ? 'is-ghost' : ''} ${isActive ? 'is-active' : ''} ${isDimmed ? 'is-dimmed' : ''}`}
        style={{ left: `${left}px`, width: `${width}px` }}
        onClick={(e) => {
          e.stopPropagation()
          onSelectClip(clip.change_id, clip.start_s)
        }}
        onMouseEnter={(e) => setHoverClip({ clip, track: trackName, x: e.clientX, y: e.clientY })}
        onMouseMove={(e) => setHoverClip(prev => prev ? { ...prev, x: e.clientX, y: e.clientY } : null)}
        onMouseLeave={() => setHoverClip(null)}
      >
        {hasHeadTrim && <span className="nle-trim-edge left" />}
        {width > 34 && <span className="nle-clip-label">{clip.name}</span>}
        {hasTailTrim && <span className="nle-trim-edge right" />}
      </div>
    )
  }

  const renderTrackStack = (side: 'overlay' | 'before' | 'after') => (
    <div className="nle-stack">
      {tracks.map((tr) => (
        <div key={`${side}-${tr.kind}-${tr.name}`} className={`nle-lane-row kind-${tr.kind}`}>
          {side === 'before' && tr.before.map(c => renderClip(c, tr.name))}
          {side === 'after' && tr.after.map(c => renderClip(c, tr.name))}
          {side === 'overlay' && (
            <>
              {tr.after.map(c => renderClip(c, tr.name))}
              {showGhosts && tr.removed.map(c => renderClip(c, tr.name, true))}
            </>
          )}
        </div>
      ))}
    </div>
  )

  const playheadX = Math.max(0, Math.min(innerW, playheadS * pxPerSec))

  return (
    <div className="nle-card">
      <div className="nle-toolbar">
        <div className="nle-seg">
          <button type="button" className={mode === 'overlay' ? 'active' : ''} onClick={() => onModeChange('overlay')}>
            Diff Overlay
          </button>
          <button type="button" className={mode === 'split' ? 'active' : ''} onClick={() => onModeChange('split')}>
            Split Before / After
          </button>
        </div>

        <label className="nle-ghost-toggle">
          <input type="checkbox" checked={showGhosts} onChange={(e) => setShowGhosts(e.target.checked)} />
          <span>Removed ghosts</span>
        </label>

        <div className="nle-zoom">
          <span>Zoom</span>
          <input type="range" min={1} max={4} step={0.25} value={zoom} onChange={(e) => setZoom(Number(e.target.value))} />
          <span className="nle-zoom-val">{zoom.toFixed(1)}×</span>
        </div>

        <div className="nle-tc-readout" title="Current scrubber position">
          {fmtTC(playheadS)} <span className="nle-tc-total">/ {fmtTC(durationS)}</span>
        </div>
      </div>

      <div className="nle-body">
        <div className="nle-headers">
          <div className="nle-ruler-corner">TC</div>
          {mode === 'overlay' ? (
            tracks.map(tr => (
              <div key={`h-${tr.kind}-${tr.name}`} className={`nle-track-hdr kind-${tr.kind}`} title={tr.name}>
                <span>{tr.short}</span>
              </div>
            ))
          ) : (
            <>
              <div className="nle-split-tag">BEFORE</div>
              {tracks.map(tr => (
                <div key={`hb-${tr.kind}-${tr.name}`} className={`nle-track-hdr kind-${tr.kind}`} title={tr.name}>
                  <span>{tr.short}</span>
                </div>
              ))}
              <div className="nle-split-tag">AFTER</div>
              {tracks.map(tr => (
                <div key={`ha-${tr.kind}-${tr.name}`} className={`nle-track-hdr kind-${tr.kind}`} title={tr.name}>
                  <span>{tr.short}</span>
                </div>
              ))}
            </>
          )}
        </div>

        <div className="nle-scroll" ref={scrollRef}>
          <div className="nle-canvas" style={{ width: `${innerW}px` }}>
            <div
              className="nle-ruler"
              onMouseDown={(e) => {
                scrubbingRef.current = true
                updateScrubFromEvent(e.clientX)
              }}
            >
              {ticks.map(t => (
                <div key={t} className="nle-tick" style={{ left: `${t * pxPerSec}px` }}>
                  <span>{fmtShortRuler(t)}</span>
                </div>
              ))}
            </div>

            {mode === 'overlay' ? (
              renderTrackStack('overlay')
            ) : (
              <>
                <div className="nle-split-bar">Previous version</div>
                {renderTrackStack('before')}
                <div className="nle-split-bar">Selected version</div>
                {renderTrackStack('after')}
              </>
            )}

            <div className="nle-playhead" style={{ left: `${playheadX}px` }}>
              <div className="nle-playhead-cap" />
            </div>
          </div>
        </div>
      </div>

      <div className="nle-legend">
        <span><i className="nle-sw u" /> Unchanged</span>
        <span><i className="nle-sw a" /> Added</span>
        <span><i className="nle-sw t" /> Trimmed</span>
        <span><i className="nle-sw r" /> Removed</span>
        <span><i className="nle-sw m" /> Moved / Modified</span>
        <span className="nle-hint">Drag ruler to scrub • 1/2 Overlay/Split • J/K Next/Prev change</span>
      </div>

      {hoverClip && (
        <div
          className="nle-tooltip"
          style={{
            left: `${Math.min(hoverClip.x + 14, window.innerWidth - 270)}px`,
            top: `${Math.max(12, hoverClip.y - 84)}px`,
          }}
        >
          <div className="nle-tt-title">{hoverClip.clip.name}</div>
          <div className="nle-tt-meta">
            {hoverClip.track} • {fmtTC(hoverClip.clip.start_s)} ({hoverClip.clip.duration_s.toFixed(2)}s)
          </div>
          {hoverClip.clip.source && <div className="nle-tt-meta">{hoverClip.clip.source}</div>}
          {hoverClip.clip.detail && <div className="nle-tt-detail">{hoverClip.clip.detail}</div>}
        </div>
      )}
    </div>
  )
}
