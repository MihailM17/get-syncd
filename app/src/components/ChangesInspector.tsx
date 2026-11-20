import type { Diff, Version } from '../types'

type Props = {
  diff: Diff | null
  selected: Version | null
  log: Version[]
  compareBase: string
  onCompareBaseChange: (base: string) => void
  diffFilter: string
  onDiffFilterChange: (filter: string) => void
  activeChangeId: number | null
  onSelectChange: (changeId: number | null, timecodeS: number | null) => void
  onPrevChange: () => void
  onNextChange: () => void
  onRestore: () => void
  onBranchFromHere: () => void
  collapsedTracks: Record<string, boolean>
  onToggleTrackCollapse: (trackKey: string) => void
  humanizeWarning: (w: string) => string
  diffError: boolean
}

export default function ChangesInspector({
  diff,
  selected,
  log,
  compareBase,
  onCompareBaseChange,
  diffFilter,
  onDiffFilterChange,
  activeChangeId,
  onSelectChange,
  onPrevChange,
  onNextChange,
  onRestore,
  onBranchFromHere,
  collapsedTracks,
  onToggleTrackCollapse,
  humanizeWarning,
  diffError,
}: Props) {
  if (!selected) {
    return (
      <div className="inspectorEmptyState">
        <p className="muted">Select a snapshot on the left to inspect timeline changes</p>
      </div>
    )
  }

  const summary = diff?.summary
  const runtimeDelta = summary?.runtime_delta_s ?? 0
  const sections = diff?.sections || []

  const matchesFilter = (type: string) => {
    if (diffFilter === 'all') return true
    if (diffFilter === 'modified') {
      return type === 'modified' || type === 'reordered' || type === 'renamed'
    }
    return type === diffFilter
  }

  return (
    <div className="changesInspectorContainer">
      {/* Snapshot Header Bar */}
      <div className="snapshotHeaderBar">
        <div className="snapshotHeaderLeft">
          <h2 className="snapshotTitle">{selected.message}</h2>
          <div className="snapshotMetaRow">
            <span className="snapshotBranchTag">{selected.timeline || 'Main Timeline'}</span>
            <span className="snapshotHash">{selected.short}</span>
            <span className="metaSeparator">•</span>

            <div className="compareBaseSelector">
              <span className="compareLabel">vs</span>
              <select
                className="compareDropdown"
                value={compareBase}
                onChange={e => onCompareBaseChange(e.target.value)}
              >
                <option value="prev">Previous Cut</option>
                <option value="empty">Empty Timeline (Initial)</option>
                {log
                  .filter(v => v.hash !== selected.hash)
                  .map(v => (
                    <option key={v.hash} value={v.hash}>
                      {v.short} — {v.message.slice(0, 32)}
                    </option>
                  ))}
              </select>
            </div>

            <span className="metaSeparator">•</span>
            <span className="snapshotDate">{selected.date}</span>
            {summary?.new_duration_s != null && summary.new_duration_s > 0 && (
              <>
                <span className="metaSeparator">•</span>
                <span className="snapshotDuration">
                  Duration: {summary.new_duration_s.toFixed(1)}s
                </span>
              </>
            )}
          </div>
        </div>

        <div className="snapshotHeaderRight">
          <button
            type="button"
            className="ghost"
            onClick={onBranchFromHere}
            title="Create a new cut/branch starting from this snapshot"
          >
            Branch from here
          </button>
          <button
            type="button"
            className="restoreBtn"
            onClick={onRestore}
            title="Restore this version into DaVinci Resolve"
          >
            Restore to Resolve
          </button>
        </div>
      </div>

      {/* Single Compact Delta Summary Bar */}
      {summary && (
        <div className="deltaBar">
          <div className="deltaPills">
            {(summary.added ?? 0) > 0 && (
              <span className="deltaPill added">+{summary.added} Added</span>
            )}
            {(summary.removed ?? 0) > 0 && (
              <span className="deltaPill removed">−{summary.removed} Removed</span>
            )}
            {(summary.trimmed ?? 0) > 0 && (
              <span className="deltaPill trimmed">~{summary.trimmed} Trimmed</span>
            )}
            {((summary.reordered ?? 0) + (summary.modified ?? 0)) > 0 && (
              <span className="deltaPill modified">
                • {(summary.reordered ?? 0) + (summary.modified ?? 0)} Modified/Moved
              </span>
            )}
            {summary.total_changes === 0 && (
              <span className="deltaPill unchanged">No changes — cuts match</span>
            )}
          </div>

          <div className="deltaRuntime">
            {Math.abs(runtimeDelta) >= 0.05 ? (
              <span className="runtimeText">
                Runtime: {runtimeDelta > 0 ? `+${runtimeDelta.toFixed(1)}s longer` : `${runtimeDelta.toFixed(1)}s shorter`}
              </span>
            ) : (
              <span className="runtimeText">Runtime: Same length</span>
            )}
          </div>
        </div>
      )}

      {/* Filter Chips & Changes Navigation Toolbar */}
      <div className="inspectorToolbar">
        <div className="filterChips">
          <button
            type="button"
            className={`filterChip ${diffFilter === 'all' ? 'active' : ''}`}
            onClick={() => onDiffFilterChange('all')}
          >
            All
          </button>
          <button
            type="button"
            className={`filterChip ${diffFilter === 'added' ? 'active' : ''}`}
            onClick={() => onDiffFilterChange('added')}
          >
            Added
          </button>
          <button
            type="button"
            className={`filterChip ${diffFilter === 'removed' ? 'active' : ''}`}
            onClick={() => onDiffFilterChange('removed')}
          >
            Removed
          </button>
          <button
            type="button"
            className={`filterChip ${diffFilter === 'trimmed' ? 'active' : ''}`}
            onClick={() => onDiffFilterChange('trimmed')}
          >
            Trimmed
          </button>
          <button
            type="button"
            className={`filterChip ${diffFilter === 'modified' ? 'active' : ''}`}
            onClick={() => onDiffFilterChange('modified')}
          >
            Modified/Moved
          </button>
        </div>

        <div className="navStepButtons">
          <button
            type="button"
            className="stepBtn"
            onClick={onPrevChange}
            title="Previous Change (K)"
          >
            <span>K ↑ Prev</span>
          </button>
          <button
            type="button"
            className="stepBtn"
            onClick={onNextChange}
            title="Next Change (J)"
          >
            <span>J ↓ Next</span>
          </button>
        </div>
      </div>

      {/* Error state */}
      {diffError && (
        <div className="note warn-note" style={{ margin: '14px 0' }}>
          Couldn’t compare these versions. Reselect to retry.
        </div>
      )}

      {/* Track Changes List */}
      <div className="trackSectionsWrapper">
        {sections.map((section, sIdx) => {
          const trackKey = `${section.kind}-${section.track}`
          const isCollapsed = Boolean(collapsedTracks[trackKey])
          const filteredEntries = section.entries.filter(e => matchesFilter(e.type))

          if (filteredEntries.length === 0 && diffFilter !== 'all') {
            return null
          }

          return (
            <div key={trackKey} className="tc-section">
              <div
                className="tc-head clickable"
                onClick={() => onToggleTrackCollapse(trackKey)}
              >
                <div className="tcHeadLeft">
                  <span className={`collapseArrow ${isCollapsed ? 'collapsed' : ''}`}>▼</span>
                  <span className="trackKindLabel">
                    {section.kind === 'text' ? 'TEXT' : section.track.toUpperCase()}
                  </span>
                </div>
                <span className="tc-count">{filteredEntries.length} items</span>
              </div>

              {!isCollapsed && (
                <div className="tcEntriesList">
                  {filteredEntries.map((e, eIdx) => {
                    const changeIds = e.change_ids || (e.change_id != null ? [e.change_id] : [])
                    const isActive = activeChangeId != null && changeIds.includes(activeChangeId)

                    return (
                      <div
                        key={`${sIdx}-${eIdx}`}
                        className={`tc-entry ${isActive ? 'is-active' : ''}`}
                        data-change-ids={changeIds.join(' ')}
                        onClick={() => onSelectChange(e.change_id ?? null, e.timecode_s)}
                      >
                        {e.label ? (
                          <>
                            <div className="tc-entry-head">
                              {e.timecode && <span className="tc-time">{e.timecode}</span>}
                              {e.timecode && <span className="tc-dash">—</span>}
                              <span className="tc-clip">{e.label}</span>
                            </div>
                            <div className="tc-lines">
                              {e.lines.map((ln, lIdx) => (
                                <div key={lIdx} className={`tc-line ${e.type}`}>
                                  <span className="tc-dot" />
                                  <span>{ln}</span>
                                </div>
                              ))}
                            </div>
                          </>
                        ) : (
                          <div className="tc-lines tc-lines-bare">
                            {e.lines.map((ln, lIdx) => (
                              <div key={lIdx} className={`tc-line ${e.type}`}>
                                <span className="tc-dot" />
                                <span>{ln}</span>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          )
        })}

        {sections.length === 0 && !diffError && (
          <div className="empty">
            {diff?.is_first_save
              ? 'Empty save — no clips in this version'
              : 'No clip changes — cuts match or only minor spacing tweaks'}
          </div>
        )}
      </div>

      {/* Warnings & Gap Notes */}
      {diff && (
        <div className="notes">
          {!diff.is_first_save &&
            (diff.changes?.filter(c => c.clip_name?.startsWith('Gap')).length || 0) > 0 && (
              <div className="note gap-note">
                • {diff.changes?.filter(c => c.clip_name?.startsWith('Gap')).length} gap
                {(diff.changes?.filter(c => c.clip_name?.startsWith('Gap')).length || 0) > 1
                  ? 's'
                  : ''}{' '}
                tweaked — spacing adjusted server-side.
              </div>
            )}
          {diff.warnings && diff.warnings.length > 0 && (
            <div className="note warn-note">
              ⚠ {diff.warnings.map(w => humanizeWarning(w)).join(' • ')}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
