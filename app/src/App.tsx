import { useEffect, useRef, useState } from 'react'
import TopBar from './components/TopBar'
import HistorySidebar from './components/HistorySidebar'
import TimelineDiffCanvas from './components/TimelineDiffCanvas'
import ChangesInspector from './components/ChangesInspector'
import CutTreeRail from './components/CutTreeRail'
import Modals from './components/Modals'
import type { Diff, Graph, ResolveCurrent, Status, TimelineInfo, Version } from './types'

let API = 'http://127.0.0.1:5174'
// Probes API_PORT_START/COUNT (5174–5183) to attach to freshest healthy server
const API_PORTS = Array.from({ length: 10 }, (_, i) => 5174 + i)
async function resolveApiBase(): Promise<string> {
  const probes = API_PORTS.map(port => (async () => {
    const ctl = new AbortController()
    const t = window.setTimeout(() => ctl.abort(), 900)
    try {
      const r = await fetch(`http://127.0.0.1:${port}/health`, { signal: ctl.signal })
      if (!r.ok) return null
      const d = await r.json() as { ok?: boolean; started?: number }
      if (!d?.ok) return null
      return { port, started: Number(d.started) || 0 }
    } catch {
      return null
    } finally {
      window.clearTimeout(t)
    }
  })())
  const found = (await Promise.all(probes)).filter(Boolean).sort((a, b) => b!.started - a!.started)[0]
  return found ? `http://127.0.0.1:${found.port}` : API
}

const POLL_MS = 10000

export default function App() {
  const [defaultRepo, setDefaultRepo] = useState('')
  const [repoReady, setRepoReady] = useState(false)
  const [repo, setRepo] = useState('')
  const [status, setStatus] = useState<Status | null>(null)
  const [log, setLog] = useState<Version[]>([])
  const [selected, setSelected] = useState<Version | null>(null)
  const [diff, setDiff] = useState<Diff | null>(null)
  const [note, setNote] = useState('')
  const [showSave, setShowSave] = useState(false)
  const [showSetup, setShowSetup] = useState(false)
  const [syncStep, setSyncStep] = useState<string | null>(null)
  const [isSyncing, setIsSyncing] = useState(false)
  const [folder, setFolder] = useState('')
  const [projects, setProjects] = useState<{ name: string; path: string }[]>([])
  const [graph, setGraph] = useState<Graph | null>(null)
  const [timelines, setTimelines] = useState<TimelineInfo[]>([])
  const [activeTimeline, setActiveTimeline] = useState<string | null>(null)
  const [showTimelinePicker, setShowTimelinePicker] = useState(false)
  const [wizardDismissed, setWizardDismissed] = useState(false)
  const [projectsLoaded, setProjectsLoaded] = useState(false)
  const [infoModal, setInfoModal] = useState<{ title: string; body: string } | null>(null)
  const [pendingForceDelete, setPendingForceDelete] = useState<string | null>(null)
  const [toast, setToast] = useState<{ msg: string; type: 'success' | 'error' | 'info' } | null>(null)
  const [diffError, setDiffError] = useState(false)
  const [apiDown, setApiDown] = useState(false)
  const [showBranch, setShowBranch] = useState(false)
  const [branchInput, setBranchInput] = useState('')
  const [newBranch, setNewBranch] = useState('')
  const [showDeleteBranch, setShowDeleteBranch] = useState<string | null>(null)
  const [showRestore, setShowRestore] = useState<Version | null>(null)
  const [showDelete, setShowDelete] = useState<Version | null>(null)

  // Calibrated Redesign States
  const [resolveCurrent, setResolveCurrent] = useState<ResolveCurrent | null>(null)
  const [compareBase, setCompareBase] = useState<string>('prev')
  const [diffMode, setDiffMode] = useState<'overlay' | 'split'>('overlay')
  const [diffFilter, setDiffFilter] = useState<string>('all')
  const [activeChangeId, setActiveChangeId] = useState<number | null>(null)
  const [playheadS, setPlayheadS] = useState<number>(0)
  const [collapsedTracks, setCollapsedTracks] = useState<Record<string, boolean>>({})
  const [searchQuery, setSearchQuery] = useState<string>('')
  const [restoreResult, setRestoreResult] = useState<{
    ok: boolean
    auto_import?: boolean
    msg: string
    filePath: string
  } | null>(null)
  const [leftSidebarOpen, setLeftSidebarOpen] = useState(true)
  const [rightSidebarOpen, setRightSidebarOpen] = useState(true)
  const [resolvePopoverOpen, setResolvePopoverOpen] = useState(false)

  const toastTimer = useRef<number | null>(null)
  const showToast = (msg: string, type: 'success' | 'error' | 'info' = 'success') => {
    setToast({ msg, type })
    if (toastTimer.current) window.clearTimeout(toastTimer.current)
    toastTimer.current = window.setTimeout(() => setToast(null), 2600)
  }

  const showInfo = (title: string, body: string, toastType: 'success' | 'error' | 'info' = 'info') => {
    setInfoModal({ title, body })
    showToast(title, toastType)
  }

  const copyText = (text: string, label: string) => {
    navigator.clipboard.writeText(text).then(
      () => showToast(`Copied ${label} to clipboard ✓`),
      () => showToast(`Could not copy ${label}`, 'error'),
    )
  }

  const audioCtx = useRef<AudioContext | null>(null)
  const playSound = (type: 'click' | 'success' | 'delete' | 'pop' = 'click') => {
    try {
      if (!audioCtx.current) {
        const AC = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext
        audioCtx.current = new AC()
      }
      const ctx = audioCtx.current
      if (ctx.state === 'suspended') void ctx.resume()
      const o = ctx.createOscillator()
      const g = ctx.createGain()
      o.connect(g)
      g.connect(ctx.destination)
      const n = ctx.currentTime
      if (type === 'click') {
        o.frequency.value = 820
        g.gain.setValueAtTime(0.13, n)
        g.gain.exponentialRampToValueAtTime(0.01, n + 0.11)
        o.start(n)
        o.stop(n + 0.12)
      } else if (type === 'success') {
        o.frequency.value = 620
        g.gain.setValueAtTime(0.16, n)
        o.frequency.exponentialRampToValueAtTime(880, n + 0.14)
        g.gain.exponentialRampToValueAtTime(0.01, n + 0.26)
        o.start(n)
        o.stop(n + 0.27)
      } else if (type === 'delete') {
        o.frequency.value = 380
        g.gain.setValueAtTime(0.14, n)
        o.frequency.exponentialRampToValueAtTime(180, n + 0.18)
        g.gain.exponentialRampToValueAtTime(0.01, n + 0.20)
        o.start(n)
        o.stop(n + 0.21)
      } else {
        o.frequency.value = 700
        g.gain.setValueAtTime(0.1, n)
        o.start(n)
        o.stop(n + 0.08)
      }
    } catch {}
    try {
      navigator.vibrate?.(type === 'delete' ? [30, 15, 30] : 12)
    } catch {}
  }

  const humanizeWarning = (w: string) => {
    if (!w) return w
    if (/^(Added|Removed|Tracks changed|Now \d)/.test(w.trim())) return w
    const listMatch = w.match(/(?:Track list changed|Tracks):\s*\[(.*?)\]\s*->\s*\[(.*?)\]/)
    if (listMatch) {
      const parseNames = (s: string) => {
        const out: string[] = []
        const re = /'([^']*)'|"([^"]*)"/g
        let m: RegExpExecArray | null
        while ((m = re.exec(s)) !== null) out.push(m[1] ?? m[2])
        return out.filter(x => x !== '')
      }
      const oldNames = parseNames(listMatch[1])
      const newNames = parseNames(listMatch[2])
      const added = newNames.filter(n => !oldNames.includes(n))
      const removed = oldNames.filter(n => !newNames.includes(n))
      const kindOf = (n: string) => (/video/i.test(n) ? 'video track' : /audio/i.test(n) ? 'audio track' : 'track')
      const group = (names: string[]) => {
        const byKind: Record<string, string[]> = {}
        for (const n of names) {
          const k = kindOf(n)
          byKind[k] = byKind[k] || []
          byKind[k].push(n)
        }
        return Object.entries(byKind).map(
          ([k, ns]) =>
            `${ns.length} ${k}${ns.length > 1 ? 's' : ''} (${
              ns.length <= 4 ? ns.join(', ') : ns.slice(0, 3).join(', ') + ` and ${ns.length - 3} more`
            })`,
        )
      }
      const parts: string[] = []
      const ag = group(added)
      const rg = group(removed)
      if (ag.length) parts.push(`Added ${ag[0]}${ag.length > 1 ? ' and ' + ag.slice(1).join(' and ') : ''}`)
      if (rg.length) {
        const r = `Removed ${rg[0]}${rg.length > 1 ? ' and ' + rg.slice(1).join(' and ') : ''}`
        parts.push(parts.length ? r[0].toLowerCase() + r.slice(1) : r)
      }
      if (parts.length) return parts.join('; ')
      return `Tracks changed — now ${newNames.length} tracks (was ${oldNames.length} tracks)`
    }
    const countMatch = w.match(/old\s*(\d+)V\/(\d+)A,\s*new\s*(\d+)V\/(\d+)A/)
    if (countMatch) {
      const [, ov, oa, nv, na] = countMatch.map(Number)
      const p = (num: number, k: string) => `${num} ${k}${num === 1 ? '' : 's'}`
      return `Now ${p(nv, 'video track')} + ${p(na, 'audio track')} (was ${p(ov, 'video track')} + ${p(oa, 'audio track')}) — only the main track is compared, check the others manually`
    }
    return w.replace(/Track list changed:/, 'Tracks changed:').replace(/auto-merge not safe/, 'check the others manually').replace(/\[|\]|'/g, '')
  }

  const timelineExplicitlySetRef = useRef(false)
  const repoRef = useRef(repo)
  repoRef.current = repo
  const activeTimelineRef = useRef<string | null>(activeTimeline)
  activeTimelineRef.current = activeTimeline

  const api = async (path: string, opts?: RequestInit, repoOverride?: string, signal?: AbortSignal) => {
    const useRepo = repoOverride ?? repoRef.current
    const url = `${API}${path}${path.includes('?') ? '&' : '?'}repo=${encodeURIComponent(useRepo)}`
    const r = await fetch(url, { ...opts, signal })
    const text = await r.text()
    let data: unknown = null
    try {
      data = text ? JSON.parse(text) : null
    } catch {
      data = { ok: false, error: text.slice(0, 200) }
    }
    if (!r.ok) {
      const msg = (data as { error?: string })?.error || `Request failed (${r.status})`
      throw new Error(msg)
    }
    return data as never
  }

  const hasAutoSelectedRef = useRef(false)
  const refreshProjects = async (signal?: AbortSignal) => {
    try {
      const r = (await fetch(`${API}/api/projects`, { signal }).then(x => {
        if (!x.ok) throw new Error(`projects failed (${x.status})`)
        return x.json()
      })) as { ok?: boolean; projects?: { name: string; path: string }[] }
      if (r.ok) {
        const projs = r.projects || []
        setProjects(projs)
        setProjectsLoaded(true)
        if (!hasAutoSelectedRef.current && projs.length && (repoRef.current === '' || repoRef.current === defaultRepo)) {
          const first = projs[0]
          if (first && first.path !== repoRef.current) {
            setRepo(first.path)
            setSelected(null)
          }
          hasAutoSelectedRef.current = true
        }
      }
    } catch (e) {
      if ((e as Error)?.name === 'AbortError') return
    }
  }

  const scanResolve = async () => {
    playSound('click')
    try {
      const r = (await fetch(`${API}/api/resolve/scan`, { method: 'POST' }).then(x => x.json())) as {
        ok?: boolean
        error?: string
        created?: string[]
        projects?: string[]
        folders?: { name: string }[]
      }
      refreshProjects()
      refresh()
      if (!r.ok) {
        playSound('pop')
        const hint = r.folders?.length ? `Existing projects: ${r.folders.map(f => f.name).join(', ')}` : ''
        showInfo(
          'Resolve not running',
          `${r.error || 'Resolve not running'}${hint ? '\n\n' + hint : ''}\n\nYou can still Create Project manually.`,
          'error',
        )
        return
      }
      playSound('success')
      showToast(r.created?.length ? `Created ${r.created.join(', ')}` : 'Scanned Resolve ✓', 'success')
      if (r.created?.length) showInfo('Projects created', `Created folders for: ${r.created.join(', ')}`, 'success')
      else if (!r.projects?.length) {
        showInfo('No Resolve projects', 'No Resolve projects found — open a project in Resolve first.', 'info')
      }
    } catch (e) {
      showInfo('Scan failed', e instanceof Error ? e.message : 'Scan failed', 'error')
    }
  }

  const syncFromResolve = async () => {
    playSound('click')
    try {
      const r = (await fetch(`${API}/api/resolve/sync?repo=${encodeURIComponent(repoRef.current)}`, { method: 'POST' }).then(
        x => x.json(),
      )) as { ok?: boolean; error?: string; timelines?: string[]; resolve_project?: string }
      if (!r.ok) {
        playSound('pop')
        showInfo('Sync from Resolve', r.error || 'Sync failed — open the matching project in Resolve first.', 'error')
        return
      }
      playSound('success')
      showToast(`Synced timelines from Resolve ✓ (${r.timelines?.length || 0})`, 'success')
      refresh()
    } catch (e) {
      showInfo('Sync failed', e instanceof Error ? e.message : 'Sync failed', 'error')
    }
  }

  const refresh = async (signal?: AbortSignal) => {
    const repoAtStart = repoRef.current
    const timelineAtStart = activeTimelineRef.current
    try {
      const s = (await api('/api/status', undefined, repoAtStart, signal)) as Status
      if (repoAtStart !== repoRef.current) return
      if (s.repo && repoAtStart && s.repo !== repoAtStart) return
      setStatus(s)
      if (!s.is_repo) {
        setShowSetup(true)
        return
      }
      setShowSetup(false)
      setApiDown(false)

      let effTimeline = timelineAtStart
      if (s.timelines) {
        setTimelines(s.timelines)
        const names = s.timelines.map(t => t.name)
        const all = s.all_timelines || names
        const isExplicitAll = timelineExplicitlySetRef.current && timelineAtStart === null
        if (!isExplicitAll && (!effTimeline || !names.includes(effTimeline))) {
          effTimeline = s.current_timeline || all[0] || s.timelines[0]?.name || null
          if (effTimeline && effTimeline !== timelineAtStart) {
            setActiveTimeline(effTimeline)
            timelineExplicitlySetRef.current = false
          }
        } else if (isExplicitAll) {
          effTimeline = null
        }
      } else {
        try {
          const t = (await api('/api/timelines', undefined, repoAtStart, signal)) as {
            ok?: boolean
            repo?: string
            timelines?: TimelineInfo[]
            current?: string | null
          }
          if (repoAtStart !== repoRef.current) return
          if (t?.ok) {
            if (t.repo && repoAtStart && t.repo !== repoAtStart) return
            setTimelines(t.timelines || [])
            if (t.current && !effTimeline) {
              effTimeline = t.current
              setActiveTimeline(t.current)
            }
          }
        } catch (e) {
          if ((e as Error)?.name === 'AbortError') return
        }
      }

      const tlParam = effTimeline ? `&timeline=${encodeURIComponent(effTimeline)}` : ''
      const l = (await api(`/api/log?limit=30${tlParam}`, undefined, repoAtStart, signal)) as Version[]
      if (repoAtStart !== repoRef.current) return
      if (Array.isArray(l)) {
        setLog(l)
        setSelected(prev => {
          if (!l.length) return null
          if (!prev) return l[0]
          const still = l.find(v => v.hash === prev.hash)
          return still ? prev : l[0]
        })
      }

      try {
        const g = (await api(
          `/api/graph/viz${effTimeline ? `?timeline=${encodeURIComponent(effTimeline)}` : ''}`,
          undefined,
          repoAtStart,
          signal,
        )) as Graph
        if (repoAtStart !== repoRef.current) return
        if (g?.ok || Array.isArray(g?.commits)) setGraph(g)
        else setGraph(null)
      } catch (e) {
        if ((e as Error)?.name !== 'AbortError' && repoAtStart === repoRef.current) setGraph(null)
      }
    } catch (e) {
      if ((e as Error)?.name === 'AbortError') return
      console.error(e)
      if (repoAtStart === repoRef.current) setApiDown(true)
    }
  }

  // Resolve sidecar address and default repo at startup
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        API = await resolveApiBase()
      } catch {}
      if (cancelled) return
      try {
        const r = await fetch(`${API}/api/default-repo`)
        const d = (await r.json()) as { ok?: boolean; path?: string }
        if (cancelled) return
        if (d?.ok && d.path) {
          setDefaultRepo(d.path)
          setRepo(prev => (prev === '' ? (d.path as string) : prev))
          setFolder(prev => (prev === '' ? (d.path as string) : prev))
        }
      } catch {} finally {
        if (!cancelled) setRepoReady(true)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  // Live Resolve Status Polling (15s timer)
  useEffect(() => {
    if (!repoReady) return
    let cancelled = false
    const loadResolveStatus = async () => {
      try {
        const r = (await fetch(`${API}/api/resolve/current`).then(x => x.json())) as ResolveCurrent
        if (!cancelled && r) setResolveCurrent(r)
      } catch {
        if (!cancelled) setResolveCurrent({ ok: false, project: null, current_timeline: null, timelines: [] })
      }
    }
    loadResolveStatus()
    const id = window.setInterval(loadResolveStatus, 15000)
    return () => {
      cancelled = true
      window.clearInterval(id)
    }
  }, [repoReady])

  // Repo switch or timeline change
  useEffect(() => {
    if (!repoReady) return
    setTimelines([])
    setLog([])
    setGraph(null)
    setSelected(null)
    setDiff(null)
    setCompareBase('prev')
    setActiveChangeId(null)
    setPlayheadS(0)
    const ctl = new AbortController()
    refreshProjects(ctl.signal)
    refresh(ctl.signal)
    const id = window.setInterval(() => {
      refreshProjects(ctl.signal)
      refresh(ctl.signal)
    }, POLL_MS)
    return () => {
      ctl.abort()
      window.clearInterval(id)
    }
  }, [repoReady, repo, activeTimeline])

  // Diff loader with arbitrary compareBase
  useEffect(() => {
    if (!selected) return
    const ctl = new AbortController()
    const idx = log.findIndex(v => v.hash === selected.hash)
    if (idx < 0) return

    const a =
      compareBase === 'prev'
        ? idx + 1 < log.length
          ? log[idx + 1].hash
          : 'empty'
        : compareBase

    const tl = activeTimeline ? `&timeline=${encodeURIComponent(activeTimeline)}` : ''
    setDiffError(false)
    setActiveChangeId(null)
    setPlayheadS(0)

    api(`/api/diff?a=${a}&b=${selected.hash}${tl}`, undefined, undefined, ctl.signal)
      .then(d => setDiff(d as Diff))
      .catch(e => {
        if ((e as Error)?.name !== 'AbortError') {
          setDiff(null)
          setDiffError(true)
        }
      })
    return () => ctl.abort()
  }, [selected, compareBase, log.length, activeTimeline])

  // Keyboard Shortcuts (⌘S, J/K, 1/2, ↑/↓, Escape)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setShowSave(false)
        setShowRestore(null)
        setShowDelete(null)
        setShowBranch(false)
        setShowDeleteBranch(null)
        setPendingForceDelete(null)
        setShowTimelinePicker(false)
        setResolvePopoverOpen(false)
        setInfoModal(null)
        return
      }

      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 's') {
        e.preventDefault()
        setShowSave(true)
        return
      }

      const tag = document.activeElement?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return

      if (e.key === '1') {
        setDiffMode('overlay')
      } else if (e.key === '2') {
        setDiffMode('split')
      } else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        if (!log.length) return
        e.preventDefault()
        const cur = selected ? log.findIndex(v => v.hash === selected.hash) : 0
        const next = Math.max(0, Math.min(log.length - 1, cur + (e.key === 'ArrowDown' ? 1 : -1)))
        setSelected(log[next])
      } else if (e.key.toLowerCase() === 'j' || e.key.toLowerCase() === 'k') {
        const flat = (diff?.sections || []).flatMap(s => s.entries)
        if (!flat.length) return
        e.preventDefault()
        const cur = flat.findIndex(en => en.change_id === activeChangeId)
        const dir = e.key.toLowerCase() === 'j' ? 1 : -1
        const next = cur < 0 ? (dir > 0 ? 0 : flat.length - 1) : (cur + dir + flat.length) % flat.length
        const target = flat[next]
        if (target.change_id != null) {
          setActiveChangeId(target.change_id)
          document
            .querySelector(`[data-change-ids~="${target.change_id}"]`)
            ?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
        }
        if (target.timecode_s != null) {
          setPlayheadS(target.timecode_s)
        }
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [log, selected, diff, activeChangeId])

  const doSave = async () => {
    playSound('click')
    setSyncStep('Preparing project...')
    await new Promise(r => setTimeout(r, 300))
    setSyncStep('Exporting timeline from Resolve...')
    try {
      const exp = await fetch(`${API}/api/export`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ repo, timeline: activeTimeline || undefined }),
      }).then(r => r.json())
      if (exp.ok) {
        playSound('pop')
        showToast(`Exported ${exp.timeline || 'timeline'} ✓`, 'success')
        setSyncStep(`Exported ✓ — ${exp.message}`)
        await new Promise(r => setTimeout(r, 300))
      } else {
        console.warn('Export failed:', exp.error)
        playSound('pop')
        setSyncStep('Export failed — try manual File → Export Timeline → OpenTimelineIO...')
        showToast('Auto-export failed — use manual export', 'info')
        await new Promise(r => setTimeout(r, 600))
      }
    } catch (e) {
      console.warn('Export call failed', e)
    }

    setSyncStep('Checking changes...')
    const st = (await api('/api/status')) as Status
    if (!st.has_changes) {
      playSound('pop')
      const wantFile =
        activeTimelineRef.current && activeTimelineRef.current !== 'timeline'
          ? `timelines/${activeTimelineRef.current}.otio`
          : 'timeline.otio'
      showInfo(
        'No changes to save',
        `Edit in Resolve, export to ${wantFile} inside the project folder, then Save again.` +
          (st.notice ? `\n\n⚠ ${st.notice}` : ''),
        'info',
      )
      setSyncStep(null)
      return
    }

    setSyncStep('Creating snapshot...')
    const res = await fetch(`${API}/api/save`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ repo, message: note || undefined, timeline: activeTimeline || undefined }),
    }).then(r => r.json())
    if (!res.ok) {
      playSound('delete')
      showInfo('Save failed', res.error, 'error')
      setSyncStep(null)
      return
    }

    const tlMsg = res.timeline ? ` · ${res.timeline}` : ''
    setSyncStep('Syncing with Git...')
    playSound('success')
    showToast(`Saved ${res.short}${tlMsg} ✓`, 'success')
    setNote('')
    setShowSave(false)
    await refresh()
    setTimeout(() => setSyncStep(null), 1000)
  }

  const confirmRestore = async () => {
    const v = showRestore
    if (!v) return
    playSound('click')
    setSyncStep(`Restoring to ${v.short}...`)
    try {
      const res = await fetch(`${API}/api/restore`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          repo,
          rev: v.hash,
          apply: true,
          timeline: activeTimeline || v.timeline || undefined,
        }),
      }).then(r => r.json())

      if (!res.ok) {
        playSound('delete')
        showInfo('Restore failed', `${res.error}\nYour current cut was not modified.`, 'error')
        setSyncStep(null)
        return
      }

      playSound('success')
      showToast(`Restored to ${v.short} ✓`, 'success')
      setSyncStep(`Restored to ${v.short} ✓`)
      setRestoreResult({
        ok: true,
        auto_import: res.auto_import,
        msg: res.auto_import_msg || '',
        filePath: res.file || res.out || `${repo}/timeline.otio`,
      })
      refresh()
      setTimeout(() => setSyncStep(null), 1200)
    } catch (e) {
      showInfo('Restore failed', e instanceof Error ? e.message : 'Restore call failed', 'error')
      setSyncStep(null)
    }
  }

  const confirmDelete = async () => {
    const v = showDelete
    if (!v) return
    setShowDelete(null)
    playSound('delete')
    setSyncStep(`Deleting ${v.short}...`)
    const res = await fetch(`${API}/api/delete`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ repo, rev: v.hash, timeline: activeTimeline || v.timeline || undefined }),
    }).then(r => r.json())
    if (!res.ok) {
      playSound('delete')
      showInfo('Delete failed', res.error, 'error')
      setSyncStep(null)
      return
    }
    playSound('delete')
    showToast(`Deleted ${v.short}`, 'success')
    setSyncStep(`Deleted ${v.short} ✓`)
    if (selected?.hash === v.hash) setSelected(null)
    refresh()
    setTimeout(() => setSyncStep(null), 1000)
  }

  const doSync = async () => {
    playSound('click')
    setIsSyncing(true)
    setSyncStep('Pushing to GitHub...')
    try {
      const s = (await api('/api/status')) as Status
      if (!s.is_repo) {
        showInfo('No project yet', 'Create Project first', 'info')
        setSyncStep(null)
        setIsSyncing(false)
        return
      }
      const r = (await api('/api/push', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      })) as { ok?: boolean; error?: string; output?: string; needs_remote?: boolean }
      if (!r?.ok) {
        playSound('delete')
        const hint = r?.needs_remote ? '\n\nConnect a GitHub remote in settings or with `gh repo create`.' : ''
        showInfo('Push failed', `${r?.error || 'Push failed.'}${hint}\nYour local cuts are safe.`, 'error')
        setSyncStep(null)
        setIsSyncing(false)
        return
      }
      playSound('success')
      showToast('Pushed to GitHub ✓', 'success')
      setSyncStep('Pushed ✓')
      refresh()
      setTimeout(() => setSyncStep(null), 1000)
    } catch (e: unknown) {
      showInfo('Push failed', (e as Error).message || 'Push failed', 'error')
      setSyncStep(null)
    } finally {
      setIsSyncing(false)
    }
  }

  const doCreate = async () => {
    const r = await fetch(`${API}/api/init`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ repo: folder }),
    }).then(res => res.json())
    if (!r.ok) showInfo('Create failed', r.error, 'error')
    else {
      setRepo(folder)
      setShowSetup(false)
      refresh()
    }
  }

  const switchBranch = () => {
    setBranchInput(status?.current_branch || 'main')
    setNewBranch('')
    setShowBranch(true)
    playSound('click')
  }

  const confirmSwitchBranch = async () => {
    const trimmed = branchInput.trim()
    if (!trimmed) return
    setShowBranch(false)
    playSound('click')
    setSyncStep(`Switching to ${trimmed}...`)
    const r = await fetch(`${API}/api/branch`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ repo, name: trimmed }),
    }).then(res => res.json())
    if (!r.ok) {
      playSound('delete')
      showInfo('Branch switch failed', r.error, 'error')
      setSyncStep(null)
      return
    }
    playSound('success')
    showToast(`Switched to cut ${trimmed} ✓`, 'success')
    refresh()
    setTimeout(() => setSyncStep(null), 1000)
  }

  const createBranch = async () => {
    const trimmed = newBranch.trim()
    if (!trimmed) return
    setShowBranch(false)
    playSound('click')
    setSyncStep(`Creating cut ${trimmed}...`)
    const r = await fetch(`${API}/api/branch`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ repo, name: trimmed }),
    }).then(res => res.json())
    if (!r.ok) {
      playSound('delete')
      showInfo('Branch create failed', r.error, 'error')
      setSyncStep(null)
      return
    }
    playSound('success')
    showToast(`Created cut ${trimmed} ✓`, 'success')
    setNewBranch('')
    refresh()
    setTimeout(() => setSyncStep(null), 1000)
  }

  const confirmDeleteBranch = async (b: string) => {
    setShowDeleteBranch(null)
    setShowBranch(false)
    playSound('delete')
    const r = await fetch(`${API}/api/branch/delete`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ repo, name: b, force: false }),
    }).then(res => res.json())
    if (!r.ok) {
      if (typeof r.error === 'string' && r.error.includes('not fully merged')) {
        setSyncStep(null)
        setPendingForceDelete(b)
        return
      } else {
        showInfo('Delete cut failed', r.error, 'error')
        setSyncStep(null)
        return
      }
    }
    showToast(`Deleted cut ${b}`, 'success')
    refresh()
  }

  const confirmForceDeleteBranch = async (b: string) => {
    setPendingForceDelete(null)
    playSound('delete')
    const r = await fetch(`${API}/api/branch/delete`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ repo, name: b, force: true }),
    }).then(res => res.json())
    if (!r.ok) {
      showInfo('Force delete failed', r.error, 'error')
      setSyncStep(null)
      return
    }
    showToast(`Force deleted cut ${b}`, 'success')
    refresh()
  }

  if (repoReady && projectsLoaded && projects.length === 0 && !wizardDismissed) {
    return (
      <FirstRunWizard
        defaultRepo={defaultRepo}
        api={api}
        notify={showInfo}
        click={playSound}
        onDismiss={() => setWizardDismissed(true)}
        onDone={path => {
          setRepo(path)
          setFolder(path)
          setShowSetup(false)
          setWizardDismissed(true)
          refreshProjects()
          refresh()
        }}
      />
    )
  }

  if (showSetup) {
    return (
      <div className="setup">
        <h1>Create Project</h1>
        <div className="card">
          <label>Project folder:</label>
          <div style={{ display: 'flex', gap: 8, marginTop: 6 }}>
            <input value={folder} onChange={e => setFolder(e.target.value)} placeholder="~/GetSyncd" />
            <button type="button" className="ghost" onClick={() => setFolder(defaultRepo)}>
              Default
            </button>
          </div>
          <div className="detect">
            <div>Target: <b>{folder || defaultRepo}</b></div>
            <div>Media: <b>stays local, never uploaded</b></div>
            <div>Timelines: <b>Git-versioned OpenTimelineIO</b></div>
            <p className="muted" style={{ marginTop: 8 }}>
              Get Syncd versions the timeline structure while keeping all video and audio files local.
            </p>
          </div>
          <button type="button" className="saveSnapshotBtn" style={{ width: '100%', justifyContent: 'center' }} onClick={doCreate}>
            Create Project
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="app">
      {/* 2-Tier Top Bar */}
      <TopBar
        status={status}
        resolveCurrent={resolveCurrent}
        projects={projects}
        currentRepo={repo}
        activeTimeline={activeTimeline}
        onSelectProject={path => {
          setRepo(path)
          setSelected(null)
          setActiveTimeline(null)
          timelineExplicitlySetRef.current = false
          playSound('click')
        }}
        onScanResolve={scanResolve}
        onSyncResolve={syncFromResolve}
        onSave={() => {
          setShowSave(true)
          playSound('click')
        }}
        onSyncGit={doSync}
        isSyncing={isSyncing}
        onSwitchBranch={switchBranch}
        onToggleLeftSidebar={() => setLeftSidebarOpen(prev => !prev)}
        onToggleRightSidebar={() => setRightSidebarOpen(prev => !prev)}
        leftSidebarOpen={leftSidebarOpen}
        rightSidebarOpen={rightSidebarOpen}
        resolvePopoverOpen={resolvePopoverOpen}
        setResolvePopoverOpen={setResolvePopoverOpen}
      />

      {syncStep && <div className="syncbar">{syncStep}</div>}
      {status?.notice && <div className="syncbar">⚠ {status.notice}</div>}
      {apiDown && <div className="syncbar">⚠ Can’t reach the helper service — is Get Syncd running? Retrying…</div>}

      <div className="main">
        {/* Left Sidebar: Timelines & Snapshots */}
        {leftSidebarOpen && (
          <HistorySidebar
            timelines={timelines}
            activeTimeline={activeTimeline}
            onSelectTimeline={tlName => {
              setActiveTimeline(tlName)
              timelineExplicitlySetRef.current = true
              playSound('click')
            }}
            log={log}
            selected={selected}
            onSelectVersion={v => {
              setSelected(v)
              playSound('click')
            }}
            onCompareVersion={hash => {
              setCompareBase(hash)
              playSound('click')
            }}
            compareBase={compareBase}
            onDeleteVersion={v => setShowDelete(v)}
            searchQuery={searchQuery}
            setSearchQuery={setSearchQuery}
          />
        )}

        {/* Center Panel: Hero Timeline Canvas & What Changed Inspector */}
        <section className="detail">
          <div className="detailInner">
            {selected ? (
              <>
                {/* Visual Multi-Track Timeline Diff Canvas */}
                <TimelineDiffCanvas
                  data={diff?.visual_tracks}
                  mode={diffMode}
                  onModeChange={setDiffMode}
                  diffFilter={diffFilter}
                  activeChangeId={activeChangeId}
                  playheadS={playheadS}
                  onPlayheadChange={setPlayheadS}
                  onSelectClip={(cid, startS) => {
                    setPlayheadS(startS)
                    setActiveChangeId(cid)
                    if (cid !== null) {
                      document
                        .querySelector(`[data-change-ids~="${cid}"]`)
                        ?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
                    }
                  }}
                />

                {/* What Changed Inspector & Delta Summary */}
                <ChangesInspector
                  diff={diff}
                  selected={selected}
                  log={log}
                  compareBase={compareBase}
                  onCompareBaseChange={setCompareBase}
                  diffFilter={diffFilter}
                  onDiffFilterChange={setDiffFilter}
                  activeChangeId={activeChangeId}
                  onSelectChange={(cid, tcS) => {
                    setActiveChangeId(cid)
                    if (tcS != null) setPlayheadS(tcS)
                  }}
                  onPrevChange={() => {
                    const flat = (diff?.sections || []).flatMap(s => s.entries)
                    if (!flat.length) return
                    const cur = flat.findIndex(en => en.change_id === activeChangeId)
                    const next = cur <= 0 ? flat.length - 1 : cur - 1
                    const target = flat[next]
                    if (target.change_id != null) setActiveChangeId(target.change_id)
                    if (target.timecode_s != null) setPlayheadS(target.timecode_s)
                  }}
                  onNextChange={() => {
                    const flat = (diff?.sections || []).flatMap(s => s.entries)
                    if (!flat.length) return
                    const cur = flat.findIndex(en => en.change_id === activeChangeId)
                    const next = cur < 0 || cur >= flat.length - 1 ? 0 : cur + 1
                    const target = flat[next]
                    if (target.change_id != null) setActiveChangeId(target.change_id)
                    if (target.timecode_s != null) setPlayheadS(target.timecode_s)
                  }}
                  onRestore={() => setShowRestore(selected)}
                  onBranchFromHere={switchBranch}
                  collapsedTracks={collapsedTracks}
                  onToggleTrackCollapse={key =>
                    setCollapsedTracks(prev => ({ ...prev, [key]: !prev[key] }))
                  }
                  humanizeWarning={humanizeWarning}
                  diffError={diffError}
                />
              </>
            ) : (
              <div className="empty">Select a snapshot on the left</div>
            )}
          </div>
        </section>

        {/* Right Sidebar: Multi-Lane Cut Tree & GitHub Remote */}
        {rightSidebarOpen && (
          <CutTreeRail
            graph={graph}
            log={log}
            status={status}
            selected={selected}
            activeTimeline={activeTimeline}
            onSelectVersion={v => {
              setSelected(v)
              playSound('click')
            }}
            onOpenNewBranch={switchBranch}
            onSyncRemote={doSync}
          />
        )}
      </div>

      {/* Upgraded Modals */}
      <Modals
        showSave={showSave}
        onCloseSave={() => setShowSave(false)}
        note={note}
        setNote={setNote}
        onConfirmSave={doSave}
        repo={repo}
        activeTimeline={activeTimeline}
        showRestore={showRestore}
        onCloseRestore={() => setShowRestore(null)}
        onConfirmRestore={confirmRestore}
        restoreResult={restoreResult}
        onResetRestoreResult={() => setRestoreResult(null)}
        showDelete={showDelete}
        onCloseDelete={() => setShowDelete(null)}
        onConfirmDelete={confirmDelete}
        showBranch={showBranch}
        onCloseBranch={() => setShowBranch(false)}
        status={status}
        branchInput={branchInput}
        setBranchInput={setBranchInput}
        onConfirmSwitchBranch={confirmSwitchBranch}
        newBranch={newBranch}
        setNewBranch={setNewBranch}
        onCreateBranch={createBranch}
        showDeleteBranch={showDeleteBranch}
        onCloseDeleteBranch={() => setShowDeleteBranch(null)}
        onConfirmDeleteBranch={confirmDeleteBranch}
        pendingForceDelete={pendingForceDelete}
        onClosePendingForceDelete={() => setPendingForceDelete(null)}
        onConfirmForceDeleteBranch={confirmForceDeleteBranch}
        showTimelinePicker={showTimelinePicker}
        onCloseTimelinePicker={() => setShowTimelinePicker(false)}
        timelines={timelines}
        onSelectTimelineFromPicker={t => {
          setActiveTimeline(t)
          timelineExplicitlySetRef.current = true
          setShowTimelinePicker(false)
          playSound('click')
        }}
        infoModal={infoModal}
        onCloseInfoModal={() => setInfoModal(null)}
        onCopyText={copyText}
      />

      {toast && <div className={`toast ${toast.type}`}>{toast.msg}</div>}
    </div>
  )
}

function FirstRunWizard(props: {
  defaultRepo: string
  api: (path: string, opts?: RequestInit, repoOverride?: string, signal?: AbortSignal) => Promise<any>
  notify: (title: string, body: string, type?: 'success' | 'error' | 'info') => void
  click: (type?: 'click' | 'success' | 'delete' | 'pop') => void
  onDismiss: () => void
  onDone: (path: string) => void
}) {
  const { defaultRepo, api, notify, click, onDismiss, onDone } = props
  const [step, setStep] = useState(0)
  const [resolveInfo, setResolveInfo] = useState<{
    project: string | null
    current_timeline: string | null
    timelines: string[]
  } | null>(null)
  const [checking, setChecking] = useState(false)
  const [projName, setProjName] = useState('')
  const [busy, setBusy] = useState(false)
  const [createdPath, setCreatedPath] = useState<string | null>(null)
  const [ghStatus, setGhStatus] = useState<{
    ok?: boolean
    has_gh?: boolean
    authed?: boolean
    error?: string
  } | null>(null)
  const [ghName, setGhName] = useState('')
  const [ghPrivate, setGhPrivate] = useState(true)
  const [ghUrl, setGhUrl] = useState<string | null>(null)

  const checkResolve = async () => {
    setChecking(true)
    try {
      const r = await fetch(`${API}/api/resolve/current`).then(x => x.json())
      setResolveInfo({
        project: r.project || null,
        current_timeline: r.current_timeline || null,
        timelines: r.timelines || [],
      })
      if (r.project && !projName) setProjName(r.project)
    } catch {
      setResolveInfo({ project: null, current_timeline: null, timelines: [] })
    } finally {
      setChecking(false)
    }
  }
  useEffect(() => {
    checkResolve()
  }, [])

  const loadGh = async () => {
    try {
      const r = await fetch(`${API}/api/github/status`).then(x => x.json())
      setGhStatus(r)
    } catch {
      setGhStatus({ ok: false, has_gh: false, authed: false, error: 'Could not reach the sidecar.' })
    }
  }
  useEffect(() => {
    if (step === 3) loadGh()
  }, [step])

  const createProject = async () => {
    const name = projName.trim()
    if (!name) {
      notify('Name required', 'Give your project a name first.', 'error')
      return
    }
    setBusy(true)
    try {
      const target = `${defaultRepo}/${name}`
      const r = (await api(
        '/api/init',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ repo: target }),
        },
        target,
      )) as { ok?: boolean; error?: string }
      if (!r?.ok) throw new Error(r?.error || 'Could not create project.')
      setCreatedPath(target)
      if (!ghName) setGhName(name)
      click('success')
      setStep(3)
    } catch (e) {
      notify('Create failed', e instanceof Error ? e.message : 'Could not create project.', 'error')
    } finally {
      setBusy(false)
    }
  }

  const createGithub = async () => {
    if (!createdPath) return
    setBusy(true)
    try {
      const r = (await api(
        '/api/github/create',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ repo: createdPath, name: ghName.trim(), private: ghPrivate }),
        },
        createdPath,
      )) as { ok?: boolean; url?: string; error?: string }
      if (!r?.ok) throw new Error(r?.error || 'Could not create repo.')
      if (r.url) setGhUrl(r.url)
      click('success')
    } catch (e) {
      notify('GitHub create failed', e instanceof Error ? e.message : 'Could not create repo.', 'error')
    } finally {
      setBusy(false)
    }
  }

  const go = (n: number) => {
    click('click')
    setStep(n)
  }
  const targetPreview = projName.trim() ? `${defaultRepo}/${projName.trim()}` : `${defaultRepo}/MyProject`

  return (
    <div className="setup">
      <h1>Get Syncd</h1>
      <div className="card" style={{ maxWidth: 520 }}>
        <div className="muted" style={{ fontSize: 12, marginBottom: 12 }}>
          Step {step + 1} of 5 {createdPath ? `· ${createdPath}` : ''}
        </div>
        {step === 0 && (
          <>
            <h3>Version control for your edits</h3>
            <p className="muted">
              Every save is a checkpoint of your timeline — see what changed in plain English and jump back to any cut.
              Your <b style={{ color: 'var(--text)' }}>media never leaves this computer</b>; only the tiny timeline file
              is versioned.
            </p>
            <div className="modalActions">
              <button
                type="button"
                className="ghost"
                onClick={() => {
                  click('click')
                  onDismiss()
                }}
              >
                Skip setup
              </button>
              <button type="button" className="saveSnapshotBtn primary big" onClick={() => go(1)}>
                Get started
              </button>
            </div>
          </>
        )}
        {step === 1 && (
          <>
            <h3>Find DaVinci Resolve</h3>
            {checking && <p className="muted">Checking for a running Resolve…</p>}
            {!checking && resolveInfo?.project && (
              <p>
                Found project <b style={{ color: 'var(--text)' }}>{resolveInfo.project}</b>
                {resolveInfo.current_timeline ? ` · timeline ${resolveInfo.current_timeline}` : ''} (
                {resolveInfo.timelines.length} timeline{resolveInfo.timelines.length === 1 ? '' : 's'}).
              </p>
            )}
            {!checking && !resolveInfo?.project && (
              <p className="muted">
                Resolve isn't reachable. Open Resolve with a project, enable Preferences → System → General → External
                scripting, then check again. You can also continue without it.
              </p>
            )}
            <div className="modalActions">
              <button type="button" className="ghost" onClick={() => go(0)}>
                Back
              </button>
              <button type="button" className="ghost" onClick={() => checkResolve()}>
                Check again
              </button>
              <button type="button" className="saveSnapshotBtn primary" onClick={() => go(2)}>
                Continue
              </button>
            </div>
          </>
        )}
        {step === 2 && (
          <>
            <h3>Create your first project</h3>
            <p className="muted">This creates a project folder with its own git history.</p>
            <label style={{ fontSize: 12, color: 'var(--muted2)' }}>Project name:</label>
            <input
              value={projName}
              onChange={e => setProjName(e.target.value)}
              placeholder={resolveInfo?.project || 'MyProject'}
              onKeyDown={e => {
                if (e.key === 'Enter') createProject()
              }}
            />
            <p className="muted" style={{ fontSize: 11, marginTop: 6 }}>
              Folder: <code>{targetPreview}</code>
            </p>
            <div className="modalActions">
              <button type="button" className="ghost" onClick={() => go(1)}>
                Back
              </button>
              <button
                type="button"
                className="saveSnapshotBtn primary"
                disabled={busy}
                onClick={createProject}
              >
                {busy ? 'Creating…' : 'Create project'}
              </button>
            </div>
          </>
        )}
        {step === 3 && (
          <>
            <h3>Back up to GitHub? (optional)</h3>
            {!ghStatus && <p className="muted">Checking GitHub CLI…</p>}
            {ghStatus && (!ghStatus.has_gh || !ghStatus.authed) && (
              <p className="muted">
                {ghStatus.error} You can do this later with <code>gh auth login</code> — local saves work fully offline either way.
              </p>
            )}
            {ghStatus?.ok && !ghUrl && (
              <>
                <label style={{ fontSize: 12, color: 'var(--muted2)' }}>Repository name:</label>
                <input
                  value={ghName}
                  onChange={e => setGhName(e.target.value)}
                  placeholder="my-film"
                />
                <label style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 10, fontSize: 12 }}>
                  <input
                    type="checkbox"
                    checked={ghPrivate}
                    onChange={e => setGhPrivate(e.target.checked)}
                  />{' '}
                  Private repository
                </label>
              </>
            )}
            {ghUrl && (
              <p>
                Created: <b style={{ color: 'var(--text)' }}>{ghUrl}</b> — pushed ✓
              </p>
            )}
            <div className="modalActions">
              <button type="button" className="ghost" onClick={() => go(2)}>
                Back
              </button>
              {ghStatus?.ok && !ghUrl && (
                <button
                  type="button"
                  className="saveSnapshotBtn primary"
                  disabled={busy || !ghName.trim()}
                  onClick={createGithub}
                >
                  {busy ? 'Creating…' : 'Create & push'}
                </button>
              )}
              <button
                type="button"
                className={ghStatus?.ok && !ghUrl ? 'ghost' : 'saveSnapshotBtn primary'}
                onClick={() => go(4)}
              >
                {ghUrl || !ghStatus?.ok ? 'Continue' : 'Skip'}
              </button>
            </div>
          </>
        )}
        {step === 4 && (
          <>
            <h3>Where things live</h3>
            <div className="detect">
              <div>Project: <b>{createdPath || targetPreview}</b></div>
              <div>Timeline: <b>auto-exported on every Save</b></div>
              <div>Media: <b>stays local, never uploaded</b></div>
              <p className="muted" style={{ marginTop: 8 }}>
                Only the small timeline file is versioned. Media paths are absolute — if you move drives, relink in
                Resolve's Media Pool as usual.
              </p>
            </div>
            <div className="modalActions">
              <button type="button" className="ghost" onClick={() => go(3)}>
                Back
              </button>
              <button
                type="button"
                className="saveSnapshotBtn primary big"
                onClick={() => {
                  click('success')
                  onDone(createdPath || targetPreview)
                }}
              >
                Open Get Syncd
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
