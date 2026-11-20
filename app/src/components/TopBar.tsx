import type { ResolveCurrent, Status } from '../types'

type Props = {
  status: Status | null
  resolveCurrent: ResolveCurrent | null
  projects: { name: string; path: string }[]
  currentRepo: string
  activeTimeline: string | null
  onSelectProject: (path: string) => void
  onScanResolve: () => void
  onSyncResolve: () => void
  onSave: () => void
  onSyncGit: () => void
  isSyncing: boolean
  onSwitchBranch: () => void
  onToggleLeftSidebar: () => void
  onToggleRightSidebar: () => void
  leftSidebarOpen: boolean
  rightSidebarOpen: boolean
  resolvePopoverOpen: boolean
  setResolvePopoverOpen: (open: boolean | ((prev: boolean) => boolean)) => void
}

export default function TopBar({
  status,
  resolveCurrent,
  projects,
  currentRepo,
  activeTimeline,
  onSelectProject,
  onScanResolve,
  onSyncResolve,
  onSave,
  onSyncGit,
  isSyncing,
  onSwitchBranch,
  onToggleLeftSidebar,
  onToggleRightSidebar,
  leftSidebarOpen,
  rightSidebarOpen,
  resolvePopoverOpen,
  setResolvePopoverOpen,
}: Props) {
  const currentProjectName = projects.find(p => p.path === currentRepo)?.name || currentRepo.split('/').pop() || 'Project'
  const isResolveConnected = Boolean(resolveCurrent?.ok && resolveCurrent?.project)
  const changedTimelines = status?.timelines?.filter(t => t.has_changes) || []
  const hasChanges = status?.has_changes || changedTimelines.length > 0

  return (
    <header className="topBarContainer">
      {/* Tier 1: 48px Header */}
      <div className="topTier1">
        <div className="topTier1Left">
          <button
            type="button"
            className="iconToggleBtn"
            onClick={onToggleLeftSidebar}
            title={leftSidebarOpen ? 'Hide History' : 'Show History'}
            aria-label="Toggle History Sidebar"
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <rect x="3" y="3" width="18" height="18" rx="2" />
              <line x1="9" y1="3" x2="9" y2="21" />
            </svg>
          </button>

          <div className="brandGroup">
            <img src="/getsyncd-icon.png" alt="Get Syncd" className="brandLogo" />
            <span className="brandName">Get Syncd</span>
          </div>

          <button
            type="button"
            className="branchPill"
            onClick={onSwitchBranch}
            title="Switch or create cut branch"
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M6 3v12" />
              <circle cx="18" cy="6" r="3" />
              <circle cx="6" cy="18" r="3" />
              <path d="M18 9a9 9 0 0 1-9 9" />
            </svg>
            <span>{status?.current_branch || 'main'}</span>
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="m6 9 6 6 6-6" />
            </svg>
          </button>

          {/* Live Resolve Status Pill */}
          <div className="resolveStatusWrapper">
            <button
              type="button"
              className={`resolveStatusPill ${isResolveConnected ? 'online' : 'offline'}`}
              onClick={() => setResolvePopoverOpen(prev => !prev)}
              title="Click to view DaVinci Resolve connection status"
            >
              <span className="statusDot" />
              <span className="resolveStatusLabel">
                {isResolveConnected ? `Resolve · ${resolveCurrent?.project}` : 'Resolve offline'}
              </span>
            </button>

            {resolvePopoverOpen && (
              <div className="resolvePopover">
                <div className="resolvePopoverHeader">
                  <span className="resolvePopoverTitle">DaVinci Resolve Connection</span>
                  <span className={`resolveStatusBadge ${isResolveConnected ? 'online' : 'offline'}`}>
                    {isResolveConnected ? 'Connected' : 'Offline'}
                  </span>
                </div>
                <div className="resolvePopoverBody">
                  {isResolveConnected ? (
                    <>
                      <div className="resolveRow">
                        <span className="resolveKey">Project:</span>
                        <span className="resolveVal">{resolveCurrent?.project}</span>
                      </div>
                      <div className="resolveRow">
                        <span className="resolveKey">Active Timeline:</span>
                        <span className="resolveVal">{resolveCurrent?.current_timeline || 'None'}</span>
                      </div>
                      <div className="resolveRow">
                        <span className="resolveKey">Timelines in Project:</span>
                        <span className="resolveVal">{resolveCurrent?.timelines.length || 0}</span>
                      </div>
                    </>
                  ) : (
                    <div className="resolveOfflineMsg">
                      Resolve scripting API not reachable. Open Resolve with a project and ensure Preferences → System → General → External scripting is enabled.
                    </div>
                  )}
                </div>
                <div className="resolvePopoverActions">
                  <button
                    type="button"
                    className="ghost small"
                    onClick={() => {
                      setResolvePopoverOpen(false)
                      onScanResolve()
                    }}
                  >
                    + Scan Resolve Projects
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>

        <div className="topTier1Right">
          {hasChanges ? (
            <span className="statusChanged">
              <span className="dotAmber" />
              {changedTimelines.length > 0
                ? `${changedTimelines.length} timeline${changedTimelines.length > 1 ? 's' : ''} changed`
                : 'Unsaved edits'}
            </span>
          ) : (
            <span className="statusUpToDate">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <polyline points="20 6 9 17 4 12" />
              </svg>
              <span>Up to date</span>
            </span>
          )}

          <button
            type="button"
            className="saveSnapshotBtn"
            onClick={onSave}
            title="Save Snapshot (⌘S / Ctrl+S)"
          >
            <span>Save Snapshot</span>
            <kbd className="keyBadge">⌘S</kbd>
          </button>

          <button
            type="button"
            className={`syncBtn ${isSyncing ? 'isSyncing' : ''}`}
            onClick={onSyncGit}
            title="Sync with GitHub Remote"
          >
            <svg
              className={isSyncing ? 'spin' : ''}
              width="13"
              height="13"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
            >
              <polyline points="23 4 23 10 17 10" />
              <polyline points="1 20 1 14 7 14" />
              <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" />
            </svg>
            <span>Sync</span>
          </button>

          <button
            type="button"
            className="iconToggleBtn"
            onClick={onToggleRightSidebar}
            title={rightSidebarOpen ? 'Hide Cut Tree' : 'Show Cut Tree'}
            aria-label="Toggle Cut Tree Sidebar"
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <rect x="3" y="3" width="18" height="18" rx="2" />
              <line x1="15" y1="3" x2="15" y2="21" />
            </svg>
          </button>
        </div>
      </div>

      {/* Tier 2: 38px Project Strip */}
      <div className="topTier2">
        <div className="topTier2Left">
          <div className="projectTabs">
            {projects.map(p => (
              <button
                key={p.path}
                type="button"
                className={`projTab ${currentRepo === p.path ? 'active' : ''}`}
                onClick={() => onSelectProject(p.path)}
              >
                {p.name}
              </button>
            ))}
            <button
              type="button"
              className="projTab action"
              onClick={onScanResolve}
              title="Scan DaVinci Resolve library and auto-create project folders"
            >
              + Scan Resolve
            </button>
            <button
              type="button"
              className="projTab action"
              onClick={onSyncResolve}
              title="Snapshot open Resolve project timeline list"
            >
              ⇅ Sync Resolve
            </button>
          </div>
        </div>

        <div className="topTier2Right">
          <span className="localPathMonospace">
            ~/GetSyncd/{currentProjectName}
            {activeTimeline && activeTimeline !== 'timeline' ? ` · timelines/${activeTimeline}.otio` : ''} · Media stays local
          </span>
        </div>
      </div>
    </header>
  )
}
