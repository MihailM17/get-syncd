import { useState } from 'react'
import type { Status, TimelineInfo, Version } from '../types'

type Props = {
  showSave: boolean
  onCloseSave: () => void
  note: string
  setNote: (n: string) => void
  onConfirmSave: () => void
  repo: string
  activeTimeline: string | null
  showRestore: Version | null
  onCloseRestore: () => void
  onConfirmRestore: () => void
  restoreResult: { ok: boolean; auto_import?: boolean; msg: string; filePath: string } | null
  onResetRestoreResult: () => void
  showDelete: Version | null
  onCloseDelete: () => void
  onConfirmDelete: () => void
  showBranch: boolean
  onCloseBranch: () => void
  status: Status | null
  branchInput: string
  setBranchInput: (b: string) => void
  onConfirmSwitchBranch: () => void
  newBranch: string
  setNewBranch: (b: string) => void
  onCreateBranch: () => void
  showDeleteBranch: string | null
  onCloseDeleteBranch: () => void
  onConfirmDeleteBranch: (branch: string) => void
  pendingForceDelete: string | null
  onClosePendingForceDelete: () => void
  onConfirmForceDeleteBranch: (branch: string) => void
  showTimelinePicker: boolean
  onCloseTimelinePicker: () => void
  timelines: TimelineInfo[]
  onSelectTimelineFromPicker: (t: string | null) => void
  infoModal: { title: string; body: string } | null
  onCloseInfoModal: () => void
  onCopyText: (text: string, label: string) => void
}

export default function Modals({
  showSave,
  onCloseSave,
  note,
  setNote,
  onConfirmSave,
  repo,
  activeTimeline,
  showRestore,
  onCloseRestore,
  onConfirmRestore,
  restoreResult,
  onResetRestoreResult,
  showDelete,
  onCloseDelete,
  onConfirmDelete,
  showBranch,
  onCloseBranch,
  status,
  branchInput,
  setBranchInput,
  onConfirmSwitchBranch,
  newBranch,
  setNewBranch,
  onCreateBranch,
  showDeleteBranch,
  onCloseDeleteBranch,
  onConfirmDeleteBranch,
  pendingForceDelete,
  onClosePendingForceDelete,
  onConfirmForceDeleteBranch,
  showTimelinePicker,
  onCloseTimelinePicker,
  timelines,
  onSelectTimelineFromPicker,
  infoModal,
  onCloseInfoModal,
  onCopyText,
}: Props) {
  const [showManualInstructions, setShowManualInstructions] = useState(false)

  const activeFilePath =
    activeTimeline && activeTimeline !== 'timeline'
      ? `${repo}/timelines/${activeTimeline}.otio`
      : `${repo}/timeline.otio`

  return (
    <>
      {/* Save Snapshot Modal */}
      {showSave && (
        <div className="modalBg" onClick={onCloseSave}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <h3>Save Snapshot</h3>
            <p className="muted" style={{ fontSize: 12 }}>
              Captures a snapshot of <b style={{ color: 'var(--text)' }}>{activeTimeline || 'current timeline'}</b>.
            </p>
            <div className="targetFileBadge" title={activeFilePath}>
              <span>Target: </span>
              <code>{activeFilePath}</code>
            </div>
            <textarea
              value={note}
              onChange={e => setNote(e.target.value)}
              placeholder="e.g. Color grade pass, trimmed scene 3, audio mix"
              rows={3}
              autoFocus
              onKeyDown={e => {
                if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
                  e.preventDefault()
                  onConfirmSave()
                }
              }}
            />
            <div className="modalActions">
              <button type="button" onClick={onCloseSave}>
                Cancel
              </button>
              <button type="button" className="primary" onClick={onConfirmSave}>
                Save Snapshot
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Upgraded 2-Step Restore Modal */}
      {showRestore && (
        <div
          className="modalBg"
          onClick={() => {
            onResetRestoreResult()
            onCloseRestore()
          }}
        >
          <div className="modal" onClick={e => e.stopPropagation()}>
            <h3>Restore to DaVinci Resolve</h3>
            <p>
              <b>{showRestore.message}</b>
              <span className="muted"> · {showRestore.short} · {showRestore.date}</span>
            </p>

            {!restoreResult ? (
              <>
                <p className="muted">
                  Restoring will rewrite the project's timeline to this cut.
                  {status?.has_changes
                    ? ' A safety snapshot of your unsaved edits will be created automatically first.'
                    : ' You can jump back to your current cut anytime.'}
                </p>
                <div className="modalActions">
                  <button type="button" onClick={onCloseRestore}>
                    Cancel
                  </button>
                  <button type="button" className="primary" onClick={onConfirmRestore}>
                    Restore Cut
                  </button>
                </div>
              </>
            ) : (
              <div className="restoreResultWrapper">
                {restoreResult.auto_import ? (
                  <div className="autoImportSuccess">
                    <div className="successBadge">✓ Auto-imported into Resolve</div>
                    <p className="muted" style={{ marginTop: 8 }}>
                      {restoreResult.msg || 'The timeline was loaded directly into your open Resolve project. Switch to Resolve to view it.'}
                    </p>
                  </div>
                ) : (
                  <div className="manualImportRequired">
                    <div className="offlineNotice">Resolve offline or auto-import unavailable</div>
                    <p className="muted">
                      The timeline OTIO file was restored to your project drive:
                    </p>
                    <div className="copyPathBox">
                      <code className="pathCode">{restoreResult.filePath}</code>
                      <button
                        type="button"
                        className="copyBtn"
                        onClick={() => onCopyText(restoreResult.filePath, 'Timeline path')}
                      >
                        Copy Path
                      </button>
                    </div>

                    <button
                      type="button"
                      className="manualToggleBtn"
                      onClick={() => setShowManualInstructions(prev => !prev)}
                    >
                      {showManualInstructions ? 'Hide instructions ▲' : 'Show Resolve import steps ▼'}
                    </button>

                    {showManualInstructions && (
                      <ol className="manualSteps">
                        <li>In DaVinci Resolve, go to: <b>File → Import Timeline → OpenTimelineIO</b></li>
                        <li>Paste or choose: <code>{restoreResult.filePath}</code></li>
                        <li>Click <b>Open</b> to create the timeline in your project.</li>
                      </ol>
                    )}
                  </div>
                )}

                <div className="modalActions" style={{ marginTop: 16 }}>
                  <button
                    type="button"
                    className="primary"
                    onClick={() => {
                      onResetRestoreResult()
                      onCloseRestore()
                    }}
                  >
                    Done
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Delete Version Modal */}
      {showDelete && (
        <div className="modalBg" onClick={onCloseDelete}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <h3>Delete Snapshot?</h3>
            <p>
              <b>{showDelete.message}</b>
              <span className="muted"> · {showDelete.short} · {showDelete.date}</span>
            </p>
            <p className="muted">
              This will remove this snapshot from history. Later saves will get new IDs.
            </p>
            <div className="modalActions">
              <button type="button" onClick={onCloseDelete}>
                Cancel
              </button>
              <button
                type="button"
                className="primary"
                style={{ background: 'var(--red)', color: 'white', borderColor: 'var(--red)' }}
                onClick={onConfirmDelete}
              >
                Delete
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Branches Modal */}
      {showBranch && !showDeleteBranch && (
        <div className="modalBg" onClick={onCloseBranch}>
          <div className="modal" onClick={e => e.stopPropagation()} style={{ maxWidth: 420 }}>
            <h3>Alternative Cuts & Branches</h3>
            <p className="muted" style={{ marginBottom: 14 }}>
              Current cut: <b style={{ color: 'var(--text)' }}>{status?.current_branch || 'main'}</b> ·{' '}
              {status?.branches?.length || 1} total
            </p>
            <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
              <select
                value={branchInput}
                onChange={e => setBranchInput(e.target.value)}
                style={{
                  flex: 1,
                  background: 'var(--bg)',
                  border: '1px solid var(--border)',
                  color: 'var(--text)',
                  padding: '9px 12px',
                  borderRadius: 'var(--radius-card)',
                  fontSize: 13,
                }}
              >
                {(status?.branches || ['main']).map(b => (
                  <option key={b} value={b}>
                    {b}
                    {b === status?.current_branch ? ' — current' : ''}
                  </option>
                ))}
              </select>
              <button type="button" className="primary" onClick={onConfirmSwitchBranch}>
                Switch
              </button>
            </div>
            <div style={{ display: 'flex', gap: 8, marginBottom: 14 }}>
              <input
                value={newBranch}
                onChange={e => setNewBranch(e.target.value)}
                placeholder="new-cut-name (e.g. director-cut)"
                style={{
                  flex: 1,
                  background: 'var(--bg)',
                  border: '1px solid var(--border)',
                  color: 'var(--text)',
                  padding: '9px 12px',
                  borderRadius: 'var(--radius-card)',
                  fontSize: 13,
                }}
                onKeyDown={e => e.key === 'Enter' && onCreateBranch()}
              />
              <button type="button" className="ghost" onClick={onCreateBranch}>
                Create
              </button>
            </div>
            {(status?.branches || []).filter(b => b !== status?.current_branch).length > 0 && (
              <div style={{ borderTop: '1px solid var(--border)', paddingTop: 12 }}>
                <div style={{ fontSize: 11, color: 'var(--muted2)', marginBottom: 8, fontWeight: 600 }}>
                  Delete Alternative Cuts
                </div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                  {(status?.branches || [])
                    .filter(b => b !== status?.current_branch)
                    .map(b => (
                      <button
                        key={b}
                        type="button"
                        onClick={() => onConfirmDeleteBranch(b)}
                        style={{
                          background: 'transparent',
                          border: '1px solid var(--border)',
                          color: 'var(--muted)',
                          padding: '5px 10px',
                          borderRadius: 'var(--radius-pill)',
                          fontSize: 12,
                          cursor: 'pointer',
                        }}
                      >
                        {b} ×
                      </button>
                    ))}
                </div>
              </div>
            )}
            <div className="modalActions" style={{ marginTop: 16 }}>
              <button type="button" onClick={onCloseBranch}>
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Delete Branch Modal */}
      {showDeleteBranch && !pendingForceDelete && (
        <div className="modalBg" onClick={onCloseDeleteBranch}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <h3>Delete cut “{showDeleteBranch}”?</h3>
            <p className="muted">
              This removes the branch reference. Commits stay in other branches, but if “{showDeleteBranch}”
              isn’t merged into “{status?.current_branch}”, those commits become unreferenced.
            </p>
            <div className="modalActions">
              <button type="button" onClick={onCloseDeleteBranch}>
                Cancel
              </button>
              <button
                type="button"
                className="primary"
                style={{ background: 'var(--red)', borderColor: 'var(--red)' }}
                onClick={() => onConfirmDeleteBranch(showDeleteBranch)}
              >
                Delete cut
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Force Delete Branch Modal */}
      {pendingForceDelete && (
        <div className="modalBg" onClick={onClosePendingForceDelete}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <h3>Force delete “{pendingForceDelete}”?</h3>
            <p className="muted">
              Cut “{pendingForceDelete}” is not fully merged. Force deleting will orphan its saves.
            </p>
            <div className="modalActions">
              <button type="button" onClick={onClosePendingForceDelete}>
                Cancel
              </button>
              <button
                type="button"
                className="primary"
                style={{ background: 'var(--red)', borderColor: 'var(--red)' }}
                onClick={() => onConfirmForceDeleteBranch(pendingForceDelete)}
              >
                Force Delete
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Timeline Picker Modal */}
      {showTimelinePicker && (
        <div className="modalBg" onClick={onCloseTimelinePicker}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <h3>Switch Active Timeline</h3>
            <p className="muted">
              Current Resolve timeline:{' '}
              <b style={{ color: 'var(--text)' }}>
                {status?.current_timeline || activeTimeline || 'None'}
              </b>
            </p>
            <div
              style={{
                display: 'flex',
                flexDirection: 'column',
                gap: 8,
                marginTop: 14,
                maxHeight: 280,
                overflow: 'auto',
              }}
            >
              <button
                type="button"
                onClick={() => onSelectTimelineFromPicker(null)}
                style={{
                  textAlign: 'left',
                  padding: '10px 12px',
                  borderRadius: 'var(--radius-card)',
                  border: !activeTimeline ? '1px solid var(--orange)' : '1px solid var(--border)',
                  background: !activeTimeline ? 'var(--orange-soft)' : 'var(--panel2)',
                  color: !activeTimeline ? 'var(--orange)' : 'var(--text)',
                  fontWeight: !activeTimeline ? 700 : 500,
                  cursor: 'pointer',
                }}
              >
                All Timelines · {timelines.length} total
              </button>

              {timelines.map(t => (
                <button
                  key={t.name}
                  type="button"
                  onClick={() => onSelectTimelineFromPicker(t.name)}
                  style={{
                    textAlign: 'left',
                    padding: '10px 12px',
                    borderRadius: 'var(--radius-card)',
                    border: activeTimeline === t.name ? '1px solid var(--orange)' : '1px solid var(--border)',
                    background: activeTimeline === t.name ? 'var(--orange-soft)' : t.has_changes ? 'var(--yellow-soft)' : 'var(--panel2)',
                    color: activeTimeline === t.name ? 'var(--orange)' : t.has_changes ? 'var(--yellow)' : 'var(--text)',
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    cursor: 'pointer',
                  }}
                >
                  <span style={{ fontWeight: activeTimeline === t.name ? 700 : 500 }}>
                    {t.name}
                    {t.name === status?.current_timeline ? ' · active in Resolve' : ''}
                  </span>
                  <span
                    style={{
                      fontSize: 11,
                      color: t.has_changes ? 'var(--orange)' : 'var(--muted)',
                      background: t.has_changes ? 'var(--orange-soft)' : 'transparent',
                      padding: t.has_changes ? '2px 6px' : '0',
                      borderRadius: 999,
                    }}
                  >
                    {t.has_changes ? '● unsaved' : 'up to date'}
                  </span>
                </button>
              ))}
            </div>
            <div className="modalActions">
              <button type="button" onClick={onCloseTimelinePicker}>
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Info Modal */}
      {infoModal && (
        <div className="modalBg" onClick={onCloseInfoModal}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <h3>{infoModal.title}</h3>
            <p className="muted" style={{ whiteSpace: 'pre-wrap', lineHeight: 1.5 }}>
              {infoModal.body}
            </p>
            <div className="modalActions">
              <button type="button" className="primary" onClick={onCloseInfoModal}>
                OK
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
