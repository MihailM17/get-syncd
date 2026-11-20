import { useMemo } from 'react'
import type { TimelineInfo, Version } from '../types'

type Props = {
  timelines: TimelineInfo[]
  activeTimeline: string | null
  onSelectTimeline: (timelineName: string | null) => void
  log: Version[]
  selected: Version | null
  onSelectVersion: (v: Version) => void
  onCompareVersion: (hash: string) => void
  compareBase: string
  onDeleteVersion: (v: Version) => void
  searchQuery: string
  setSearchQuery: (q: string) => void
}

export default function HistorySidebar({
  timelines,
  activeTimeline,
  onSelectTimeline,
  log,
  selected,
  onSelectVersion,
  onCompareVersion,
  compareBase,
  onDeleteVersion,
  searchQuery,
  setSearchQuery,
}: Props) {
  const filteredLog = useMemo(() => {
    if (!searchQuery.trim()) return log
    const q = searchQuery.toLowerCase()
    return log.filter(
      v =>
        v.message.toLowerCase().includes(q) ||
        v.short.toLowerCase().includes(q) ||
        (v.timeline && v.timeline.toLowerCase().includes(q)),
    )
  }, [log, searchQuery])

  const groups = useMemo(() => {
    const today = new Date().toISOString().slice(0, 10)
    const yest = new Date(Date.now() - 864e5).toISOString().slice(0, 10)
    const out: Record<string, Version[]> = {}
    for (const v of filteredLog) {
      let k = v.date
      if (k === today) k = 'Today'
      else if (k === yest) k = 'Yesterday'
      out[k] = out[k] || []
      out[k].push(v)
    }
    return out
  }, [filteredLog])

  return (
    <aside className="historySidebar">
      {/* Timelines Section */}
      <div className="sidebarSection timelinesSection">
        <div className="sidebarHeaderRow">
          <span className="sidebarTitle">Timelines</span>
          {activeTimeline && <span className="activeTlBadge">{activeTimeline}</span>}
        </div>

        <div className="timelineList">
          <button
            type="button"
            className={`timelineItemBtn ${activeTimeline === null ? 'active' : ''}`}
            onClick={() => onSelectTimeline(null)}
          >
            <span className="timelineItemName">All Timelines</span>
            <span className="timelineItemCount">{timelines.length}</span>
          </button>

          {timelines.map(t => (
            <button
              key={t.file || t.name}
              type="button"
              className={`timelineItemBtn ${activeTimeline === t.name ? 'active' : ''} ${t.has_changes ? 'hasChanges' : ''}`}
              onClick={() => onSelectTimeline(t.name)}
            >
              <div className="timelineItemLeft">
                {t.has_changes && <span className="dotAmberSmall" title="Unsaved changes in this timeline" />}
                <span className="timelineItemName">{t.name}</span>
              </div>
              <span className="timelineItemStatus">
                {t.has_changes ? 'unsaved' : ''}
              </span>
            </button>
          ))}
        </div>
      </div>

      {/* Snapshots Section */}
      <div className="sidebarSection snapshotsSection">
        <div className="sidebarHeaderRow">
          <span className="sidebarTitle">Snapshots</span>
          <span className="snapshotsCount">{filteredLog.length} saves</span>
        </div>

        {/* Filter Input */}
        <div className="snapshotFilterWrapper">
          <input
            type="text"
            className="snapshotFilterInput"
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            placeholder="Search notes, hash, timeline..."
          />
          {searchQuery && (
            <button
              type="button"
              className="clearSearchBtn"
              onClick={() => setSearchQuery('')}
            >
              ×
            </button>
          )}
        </div>

        {/* Grouped Snapshot List */}
        <div className="snapshotScrollList">
          {Object.entries(groups).map(([dateLabel, versions]) => (
            <div key={dateLabel} className="snapshotGroup">
              <div className="gdate">{dateLabel}</div>
              {versions.map(v => {
                const isSelected = selected?.hash === v.hash
                const isComparingThis = compareBase === v.hash

                return (
                  <div
                    key={v.hash}
                    className={`row ${isSelected ? 'sel' : ''}`}
                    onClick={() => onSelectVersion(v)}
                  >
                    <div className="thumb">
                      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <rect x="2" y="2" width="20" height="20" rx="2.18" />
                        <line x1="7" y1="2" x2="7" y2="22" />
                        <line x1="17" y1="2" x2="17" y2="22" />
                        <line x1="2" y1="12" x2="22" y2="12" />
                      </svg>
                    </div>

                    <div className="meta">
                      <div className="msg" title={v.message}>
                        <span className="msgText">{v.message}</span>
                        {!activeTimeline && v.timeline && v.timeline !== 'timeline' && (
                          <span className="tlTag">{v.timeline}</span>
                        )}
                        {v.legacy && <span className="sharedTag">shared</span>}
                      </div>
                      <div className="sub">
                        <span>{v.date} · {v.short}</span>
                      </div>
                    </div>

                    <div className="rowActions">
                      {!isSelected && (
                        <button
                          type="button"
                          className={`compareBtn ${isComparingThis ? 'active' : ''}`}
                          title={`Compare selected cut against ${v.short}`}
                          onClick={e => {
                            e.stopPropagation()
                            onCompareVersion(v.hash)
                          }}
                        >
                          {isComparingThis ? 'Comparing' : 'Compare'}
                        </button>
                      )}
                      <button
                        type="button"
                        className="delBtn"
                        title="Delete snapshot"
                        aria-label={`Delete ${v.short}`}
                        onClick={e => {
                          e.stopPropagation()
                          onDeleteVersion(v)
                        }}
                      >
                        ×
                      </button>
                    </div>
                  </div>
                )
              })}
            </div>
          ))}

          {filteredLog.length === 0 && (
            <div className="empty">
              {searchQuery ? 'No matching snapshots found' : 'No snapshots yet — save one above'}
            </div>
          )}
        </div>
      </div>

      {/* Footer */}
      <footer className="historySidebarFooter">
        <span className="privacyNotice">Media stays local · Git versioned</span>
      </footer>
    </aside>
  )
}
