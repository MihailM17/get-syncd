import { useEffect, useRef, useState } from 'react'
import './App.css'

const API = 'http://127.0.0.1:5174'
// Projects folder comes from GET /api/default-repo at startup (OS-correct ~/GetSyncd).
// Empty until resolved — the backend treats an empty repo as "use the default".
const POLL_MS = 10000

type Version = { hash: string; short: string; author: string; date: string; message: string; preview?: string; timeline?: string }
type TimelineInfo = { name: string; file: string; has_changes: boolean | null; message: string; stat?: string }
type Status = { repo?: string; is_repo: boolean; has_changes: boolean | null; message: string; candidate?: string; current_branch?: string; branches?: string[], timelines?: TimelineInfo[], current_timeline?: string | null, all_timelines?: string[] }
type GraphCommit = { hash: string; short: string; message: string; relative?: string; date: string; lane?: number; isBranch?: boolean; isFork?: boolean; isCurrent?: boolean; branches?: string[] }
type Graph = { ok?: boolean; current?: string; branches?: string[]; altBranch?: string | null; fork?: string | null; commits?: GraphCommit[] }
type DiffChange = { type: string; index_old?: number | null; index_new?: number | null; clip_name?: string; kind?: string; details?: Record<string, number | string | boolean | undefined> }
type Diff = { summary?: { added?: number; removed?: number; trimmed?: number; reordered?: number; gap_changed?: number; total_changes?: number; runtime_delta_s?: number }; changes?: DiffChange[]; warnings?: string[]; new_track?: { items?: { name?: string }[] } | null }

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
  const [folder, setFolder] = useState('')
  const [projects, setProjects] = useState<{name:string,path:string}[]>([])
  const [graph, setGraph] = useState<Graph | null>(null)
  const [timelines, setTimelines] = useState<TimelineInfo[]>([])
  const [activeTimeline, setActiveTimeline] = useState<string | null>(null)
  const [showTimelinePicker, setShowTimelinePicker] = useState(false)
  const [showAllChanges, setShowAllChanges] = useState(false)
  const [wizardDismissed, setWizardDismissed] = useState(false)
  const [projectsLoaded, setProjectsLoaded] = useState(false)
  const [infoModal, setInfoModal] = useState<{title:string, body:string} | null>(null)
  const [pendingForceDelete, setPendingForceDelete] = useState<string | null>(null)
  const [toast, setToast] = useState<{msg:string, type:'success'|'error'|'info'}|null>(null)
  const toastTimer = useRef<number | null>(null)
  const showToast = (msg:string, type:'success'|'error'|'info'='success') => {
    setToast({msg, type})
    if (toastTimer.current) window.clearTimeout(toastTimer.current)
    toastTimer.current = window.setTimeout(()=>setToast(null), 2600)
  }
  const showInfo = (title:string, body:string, toastType:'success'|'error'|'info'='info') => {
    setInfoModal({title, body})
    showToast(title, toastType)
  }
  const audioCtx = useRef<AudioContext | null>(null)
  const playSound = (type:'click'|'success'|'delete'|'pop'='click') => {
    try {
      if (!audioCtx.current) {
        const AC = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext
        audioCtx.current = new AC()
      }
      const ctx = audioCtx.current
      if (ctx.state === 'suspended') void ctx.resume()
      const o = ctx.createOscillator(); const g = ctx.createGain(); o.connect(g); g.connect(ctx.destination)
      const n = ctx.currentTime
      if (type==='click') { o.frequency.value=820; g.gain.setValueAtTime(0.13, n); g.gain.exponentialRampToValueAtTime(0.01, n+0.11); o.start(n); o.stop(n+0.12) }
      else if (type==='success') { o.frequency.value=620; g.gain.setValueAtTime(0.16, n); o.frequency.exponentialRampToValueAtTime(880, n+0.14); g.gain.exponentialRampToValueAtTime(0.01, n+0.26); o.start(n); o.stop(n+0.27) }
      else if (type==='delete') { o.frequency.value=380; g.gain.setValueAtTime(0.14, n); o.frequency.exponentialRampToValueAtTime(180, n+0.18); g.gain.exponentialRampToValueAtTime(0.01, n+0.20); o.start(n); o.stop(n+0.21) }
      else { o.frequency.value=700; g.gain.setValueAtTime(0.1, n); o.start(n); o.stop(n+0.08) }
    } catch {}
    try { navigator.vibrate?.(type==='delete'?[30,15,30]:12) } catch {}
  }
  const humanSummary = (s:any) => {
    if (!s || s.total_changes===0) return "No changes — timelines match perfectly"
    const p:string[]=[]
    if (s.added) p.push(`${s.added} ${s.added===1?'clip added':'clips added'}`)
    if (s.removed) p.push(`${s.removed} ${s.removed===1?'clip removed':'clips removed'}`)
    if (s.trimmed) p.push(`${s.trimmed} ${s.trimmed===1?'clip trimmed':'clips trimmed'}`)
    if (s.reordered) p.push(`${s.reordered} moved`)
    if (s.gap_changed) p.push(`${s.gap_changed} gap${s.gap_changed>1?'s':''} tweaked`)
    let t = p.join(' • ')
    const d = s.runtime_delta_s || 0
    if (Math.abs(d) >= 0.05) {
      const sign = d>0?'+':''
      t += ` • ${sign}${d.toFixed(1)}s ${d>0?'longer':'shorter'}`
    } else t += ` • same length`
    return t.charAt(0).toUpperCase() + t.slice(1)
  }
  const humanChange = (c:any) => {
    const raw = c.clip_name || 'Clip'
    const isGap = raw.startsWith('Gap') || c.kind==='gap'
    const name = isGap ? 'a gap' : `"${raw}"`
    const d = c.details || {}
    if (c.type==='added') return `Added ${name}${d.duration_s ? ` • ${d.duration_s.toFixed(1)}s` : ''}`
    if (c.type==='removed') return `Removed ${name}`
    if (c.type==='trimmed') {
      const delta = d.delta_s || 0
      const sign = delta>=0?'+':''
      const o = d.old_duration_s?.toFixed(1) || '?'
      const n = d.new_duration_s?.toFixed(1) || '?'
      if (isGap) return `Gap length ${o}s → ${n}s`
      return `Trimmed ${name} ${sign}${delta.toFixed(1)}s • now ${n}s (was ${o}s)`
    }
    if (c.type==='reordered') return `Moved ${name} to a new spot`
    if (c.type==='gap_changed') return `Gap ${name} changed`
    return `${c.type} ${name}`
  }
  const humanizeWarning = (w:string) => {
    if (!w) return w
    // Already human-friendly (new backend) — pass through
    if (/^(Added|Removed|Tracks changed|Now \d)/.test(w.trim())) return w
    // Legacy: "Track list changed: ['Video 1', ...] -> [...]" or "Tracks: [...] -> [...]"
    const listMatch = w.match(/(?:Track list changed|Tracks):\s*\[(.*?)\]\s*->\s*\[(.*?)\]/)
    if (listMatch) {
      const parseNames = (s:string) => {
        const out:string[] = []
        const re = /'([^']*)'|"([^"]*)"/g
        let m:any
        while ((m = re.exec(s)) !== null) out.push(m[1] ?? m[2])
        return out.filter(x=>x!=='')
      }
      const oldNames = parseNames(listMatch[1])
      const newNames = parseNames(listMatch[2])
      const added = newNames.filter(n=>!oldNames.includes(n))
      const removed = oldNames.filter(n=>!newNames.includes(n))
      const kindOf = (n:string) => /video/i.test(n) ? 'video track' : /audio/i.test(n) ? 'audio track' : 'track'
      const group = (names:string[]) => {
        const byKind: Record<string,string[]> = {}
        for (const n of names) {
          const k = kindOf(n)
          byKind[k] = byKind[k] || []
          byKind[k].push(n)
        }
        return Object.entries(byKind).map(([k, ns]) => `${ns.length} ${k}${ns.length>1?'s':''} (${ns.length<=4?ns.join(', '):ns.slice(0,3).join(', ')+` and ${ns.length-3} more`})`)
      }
      const parts:string[] = []
      const ag = group(added)
      const rg = group(removed)
      if (ag.length) parts.push(`Added ${ag[0]}${ag.length>1?' and '+ag.slice(1).join(' and '):''}`)
      if (rg.length) {
        const r = `Removed ${rg[0]}${rg.length>1?' and '+rg.slice(1).join(' and '):''}`
        parts.push(parts.length ? r[0].toLowerCase()+r.slice(1) : r)
      }
      if (parts.length) return parts.join('; ')
      return `Tracks changed — now ${newNames.length} tracks (was ${oldNames.length} tracks)`
    }
    // Legacy: "Track counts differ: old 1V/2A, new 3V/3A — ..."
    const countMatch = w.match(/old\s*(\d+)V\/(\d+)A,\s*new\s*(\d+)V\/(\d+)A/)
    if (countMatch) {
      const [, ov, oa, nv, na] = countMatch.map(Number)
      const p = (n:number,k:string) => `${n} ${k}${n===1?'':'s'}`
      return `Now ${p(nv,'video track')} + ${p(na,'audio track')} (was ${p(ov,'video track')} + ${p(oa,'audio track')}) — only the main track is compared, check the others manually`
    }
    // Final safety net: never show raw Python arrays
    return w.replace(/Track list changed:/, 'Tracks changed:').replace(/auto-merge not safe/, 'check the others manually').replace(/\[|\]|'/g, '')
  }

  const api = async (path: string, opts?: RequestInit, repoOverride?: string, signal?: AbortSignal) => {
    const useRepo = repoOverride ?? repoRef.current
    const url = `${API}${path}${path.includes('?') ? '&' : '?'}repo=${encodeURIComponent(useRepo)}`
    const r = await fetch(url, { ...opts, signal })
    const text = await r.text()
    let data: unknown = null
    try { data = text ? JSON.parse(text) : null } catch { data = { ok: false, error: text.slice(0, 200) } }
    if (!r.ok) {
      const msg = (data as { error?: string })?.error || `Request failed (${r.status})`
      throw new Error(msg)
    }
    return data as never
  }

  const hasAutoSelectedRef = useRef(false)
  const refreshProjects = async (signal?: AbortSignal) => {
    try {
      const r = await fetch(`${API}/api/projects`, { signal }).then(x=>{
        if (!x.ok) throw new Error(`projects failed (${x.status})`)
        return x.json()
      }) as { ok?: boolean; projects?: {name:string,path:string}[] }
      if (r.ok) {
        const projs = r.projects || []
        setProjects(projs)
        setProjectsLoaded(true)
        // First load only: if still on container path, switch to first project (no N+1 log fan-out)
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
      const r = await fetch(`${API}/api/resolve/scan`, {method:'POST'}).then(x=>x.json()) as { ok?: boolean; error?: string; created?: string[]; projects?: string[]; folders?: {name:string}[] }
      refreshProjects(); refresh()
      if (!r.ok) {
        playSound('pop')
        const hint = r.folders?.length ? `Existing projects: ${r.folders.map(f=>f.name).join(', ')}` : ''
        showInfo('Resolve not running', `${r.error || 'Resolve not running'}${hint ? '\n\n' + hint : ''}\n\nYou can still Create Project manually.`, 'error')
        return
      }
      playSound('success'); showToast(r.created?.length ? `Created ${r.created.join(', ')}` : 'Scanned Resolve ✓', 'success')
      if (r.created?.length) showInfo('Projects created', `Created folders for: ${r.created.join(', ')}`, 'success')
      else if (!r.projects?.length) showInfo('No Resolve projects', 'No Resolve projects found — open a project in Resolve first. Existing GetSyncd projects shown.', 'info')
    } catch (e) {
      showInfo('Scan failed', e instanceof Error ? e.message : 'Scan failed', 'error')
    }
  }

  const syncFromResolve = async () => {
    playSound('click')
    try {
      const r = await fetch(`${API}/api/resolve/sync?repo=${encodeURIComponent(repoRef.current)}`, {method:'POST'}).then(x=>x.json()) as { ok?: boolean; error?: string; timelines?: string[]; resolve_project?: string }
      if (!r.ok) {
        playSound('pop')
        showInfo('Sync from Resolve', r.error || 'Sync failed — open the matching project in Resolve first.', 'error')
        return
      }
      playSound('success'); showToast(`Synced timelines from Resolve ✓ (${r.timelines?.length || 0})`, 'success')
      refresh()
    } catch (e) {
      showInfo('Sync failed', e instanceof Error ? e.message : 'Sync failed', 'error')
    }
  }

  const [showRestore, setShowRestore] = useState<Version | null>(null)
  const [showDelete, setShowDelete] = useState<Version | null>(null)
  const timelineExplicitlySetRef = useRef(false)
  const repoRef = useRef(repo)
  repoRef.current = repo
  const activeTimelineRef = useRef<string | null>(activeTimeline)
  activeTimelineRef.current = activeTimeline

  const refresh = async (signal?: AbortSignal) => {
    const repoAtStart = repoRef.current
    const timelineAtStart = activeTimelineRef.current
    try {
      const s = await api('/api/status', undefined, repoAtStart, signal) as Status
      // Guard against stale response after repo switch — strict per-project isolation
      if (repoAtStart !== repoRef.current) return
      if (s.repo && repoAtStart && s.repo !== repoAtStart) return
      setStatus(s)
      if (!s.is_repo) { setShowSetup(true); return }
      setShowSetup(false)
      // Determine effective timeline for this refresh — strictly per-project
      let effTimeline = timelineAtStart
      if (s.timelines) {
        // Extra guard: ensure timelines belong to this repo (s.repo matches)
        setTimelines(s.timelines)
        const names = (s.timelines as any[]).map((t:any)=>t.name)
        const all = s.all_timelines || names
        // Only auto-set activeTimeline on first load or when repo changed and no explicit choice
        const isExplicitAll = timelineExplicitlySetRef.current && timelineAtStart === null
        if (!isExplicitAll && (!effTimeline || !names.includes(effTimeline))) {
          effTimeline = s.current_timeline || (all[0] as any) || (s.timelines[0] as any)?.name || null
          if (effTimeline && effTimeline !== timelineAtStart) {
            setActiveTimeline(effTimeline)
            timelineExplicitlySetRef.current = false
          }
        } else if (isExplicitAll) {
          effTimeline = null
        }
      } else {
        try {
          const t = await api('/api/timelines', undefined, repoAtStart, signal) as { ok?: boolean; repo?: string; timelines?: TimelineInfo[]; current?: string | null }
          if (repoAtStart !== repoRef.current) return
          if (t?.ok) {
            // Guard: t.repo should match repoAtStart if present
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
      // Use effTimeline consistently for both log and graph — strict per-timeline filtering
      const tlParam = effTimeline ? `&timeline=${encodeURIComponent(effTimeline)}` : ''
      const l = await api(`/api/log?limit=30${tlParam}`, undefined, repoAtStart, signal) as Version[]
      if (repoAtStart !== repoRef.current) return
      if (Array.isArray(l)) {
        setLog(l)
        setSelected(prev => {
          if (!l.length) return null
          if (!prev) return l[0]
          const still = l.find((v:Version)=>v.hash===prev.hash)
          return still ? prev : l[0]
        })
      }
      try {
        const g = await api(`/api/graph/viz${effTimeline?`?timeline=${encodeURIComponent(effTimeline)}`:''}`, undefined, repoAtStart, signal) as Graph
        if (repoAtStart !== repoRef.current) return
        if (g?.ok) setGraph(g)
        else if (Array.isArray(g?.commits)) setGraph(g)
        else setGraph(null)
      } catch (e) { if ((e as Error)?.name !== 'AbortError' && repoAtStart === repoRef.current) setGraph(null) }
    } catch (e) {
      if ((e as Error)?.name === 'AbortError') return
      console.error(e)
    }
  }

  // Resolve OS-correct ~/GetSyncd once at startup (replaces hardcoded fallback path)
  useEffect(() => {
    let cancelled = false
    fetch(`${API}/api/default-repo`).then(r=>r.json()).then((d:{ok?:boolean; path?:string})=>{
      if (cancelled) return
      if (d?.ok && d.path) {
        setDefaultRepo(d.path)
        setRepo(prev => (prev === '' ? d.path as string : prev))
        setFolder(prev => (prev === '' ? d.path as string : prev))
      }
    }).catch(()=>{}).finally(()=>{ if (!cancelled) setRepoReady(true) })
    return ()=>{ cancelled = true }
  }, [])

  useEffect(() => {
    if (!repoReady) return
    // Clear stale per-project state immediately on repo switch — prevents flash of old timelines/commits
    setTimelines([])
    setLog([])
    setGraph(null)
    setSelected(null)
    setDiff(null)
    setShowAllChanges(false)
    const ctl = new AbortController()
    refreshProjects(ctl.signal); refresh(ctl.signal)
    const id = window.setInterval(()=>{ refreshProjects(ctl.signal); refresh(ctl.signal) }, POLL_MS)
    return ()=>{ ctl.abort(); window.clearInterval(id) }
  }, [repoReady, repo, activeTimeline])
  useEffect(() => {
    if (!selected || log.length<2) return
    const ctl = new AbortController()
    const idx = log.findIndex(v=>v.hash===selected.hash)
    const a = idx+1<log.length ? log[idx+1].hash : selected.hash
    const tl = activeTimelineRef.current ? `&timeline=${encodeURIComponent(activeTimelineRef.current)}` : ''
    api(`/api/diff?a=${a}&b=${selected.hash}${tl}`, undefined, undefined, ctl.signal).then(d=>setDiff(d as Diff)).catch(e=>{ if ((e as Error)?.name !== 'AbortError') setDiff(null) })
    return ()=>ctl.abort()
  }, [selected, log.length])

  const doSave = async () => {
    playSound('click')
    setSyncStep('Preparing project...')
    await new Promise(r=>setTimeout(r,400))
    setSyncStep('Exporting timeline from Resolve...')
    try {
      const exp = await fetch(`${API}/api/export`, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({repo, timeline: activeTimeline || undefined})}).then(r=>r.json())
      if (exp.ok) {
        playSound('pop'); showToast(`Exported ${exp.timeline || 'timeline'} ✓`, 'success')
        setSyncStep(`Exported ✓ — ${exp.message}`)
        await new Promise(r=>setTimeout(r,400))
      } else {
        console.warn('Export failed:', exp.error)
        playSound('pop')
        setSyncStep('Export failed — try manual File → Export Timeline → OpenTimelineIO...')
        showToast('Auto-export failed — use manual export', 'info')
        await new Promise(r=>setTimeout(r,900))
      }
    } catch (e) {
      console.warn('Export call failed', e)
    }
    setSyncStep('Checking changes...')
    const st = await api('/api/status') as Status
    if (!st.has_changes) { playSound('pop'); showInfo('No changes to save', 'Edit in Resolve and re-export ~/GetSyncd/timeline.otio first' + (st.message?.includes('Found') ? `\n\nFound: ${st.candidate || ''}` : ''), 'info'); setSyncStep(null); return }
    setSyncStep('Creating version...')
    const res = await fetch(`${API}/api/save`, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({repo, message: note || undefined, timeline: activeTimeline || undefined})}).then(r=>r.json())
    if (!res.ok) { playSound('delete'); showInfo('Save failed', res.error, 'error'); setSyncStep(null); return }
    // Show which timeline was saved
    const tlMsg = res.timeline ? ` • ${res.timeline}` : ''
    setSyncStep('Syncing with GitHub...')
    playSound('success'); showToast(`Saved ${res.short}${tlMsg} ✓`, 'success')
    await new Promise(r=>setTimeout(r,600))
    try { await fetch(`${API}/api/status?repo=${encodeURIComponent(repo)}`) } catch {}
    setSyncStep('Complete ✓')
    setNote(''); setShowSave(false)
    await refresh()
    setTimeout(()=>setSyncStep(null), 1200)
  }

  const doRestore = (v: Version) => setShowRestore(v)
  const confirmRestore = async () => {
    const v = showRestore
    if (!v) return
    setShowRestore(null)
    playSound('click')
    setSyncStep(`Restoring to ${v.short}...`)
    const res = await fetch(`${API}/api/restore`, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({repo, rev: v.hash, apply: true, timeline: activeTimeline || v.timeline || undefined})}).then(r=>r.json())
    if (!res.ok) { playSound('delete'); showInfo('Restore failed', `${res.error}\nYour current work was not deleted.`, 'error'); setSyncStep(null); return }
    playSound('success'); showToast(`Restored to ${v.short} ✓`, 'success')
    setSyncStep(`Restored to ${v.short} ✓`)
    refresh()
    setTimeout(()=>setSyncStep(null), 1500)
    if (res.auto_import) {
      showInfo(`Restored to ${v.short}`, `${res.auto_import_msg}\n\nNo manual import needed — just play the timeline in Resolve.`, 'success')
    } else {
      showInfo(`Restored to ${v.short}`, `${res.auto_import_msg || ''}\n\nIn Resolve: File → Import Timeline → OpenTimelineIO → timeline.otio`, 'success')
    }
  }

  const doDelete = (v: Version) => setShowDelete(v)
  const confirmDelete = async () => {
    const v = showDelete
    if (!v) return
    setShowDelete(null)
    playSound('delete')
    setSyncStep(`Deleting ${v.short}...`)
    const res = await fetch(`${API}/api/delete`, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({repo, rev: v.hash, timeline: activeTimeline || v.timeline || undefined})}).then(r=>r.json())
    if (!res.ok) { playSound('delete'); showInfo('Delete failed', res.error, 'error'); setSyncStep(null); return }
    playSound('delete'); showToast(`Deleted ${v.short}`, 'success')
    setSyncStep(`Deleted ${v.short} ✓`)
    if (selected?.hash === v.hash) setSelected(null)
    refresh()
    setTimeout(()=>setSyncStep(null), 1200)
  }

  const doSync = async () => {
    setSyncStep('Syncing with GitHub...')
    // naive: try push via CLI? For now just status
    try {
      const s = await api('/api/status') as Status
      if (!s.is_repo) { showInfo('No project yet', 'Create Project first', 'info'); setSyncStep(null); return }
      // In real app, call POST /api/push
      setSyncStep('Complete ✓')
      setTimeout(()=>setSyncStep(null), 1200)
    } catch (e:any) {
      showInfo('Sync failed', `Your local project has not been deleted.\n${e.message}`, 'error')
      setSyncStep(null)
    }
  }

  const doCreate = async () => {
    const r = await fetch(`${API}/api/init`, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({repo: folder})}).then(r=>r.json())
    if (!r.ok) showInfo('Create failed', r.error, 'error')
    else { setRepo(folder); setShowSetup(false); refresh() }
  }

  const groups: Record<string, Version[]> = {}
  const today = new Date().toISOString().slice(0,10)
  const yest = new Date(Date.now()-864e5).toISOString().slice(0,10)
  for (const v of log) {
    let k = v.date
    if (k===today) k='Today'
    else if (k===yest) k='Yesterday'
    groups[k] = groups[k] || []
    groups[k].push(v)
  }

  if (repoReady && projectsLoaded && projects.length===0 && !wizardDismissed) {
    return (
      <FirstRunWizard
        defaultRepo={defaultRepo}
        api={api}
        notify={showInfo}
        click={playSound}
        onDismiss={()=>setWizardDismissed(true)}
        onDone={(path)=>{
          setRepo(path); setFolder(path); setShowSetup(false); setWizardDismissed(true)
          refreshProjects(); refresh()
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
          <div className="row">
            <input value={folder} onChange={e=>setFolder(e.target.value)} placeholder="~/GetSyncd" />
            <button onClick={()=>setFolder(defaultRepo)}>Select Folder</button>
          </div>
          <div className="detect">
            <div>Detected:</div>
            <div>DaVinci Resolve project</div>
            <div>Media: <b>keeps local (164 GB example)</b></div>
            <div>Timeline: <b>32 MB — will be versioned</b></div>
            <p className="muted">Get Syncd will version the timeline while keeping your media files local.</p>
          </div>
          <button className="primary big" onClick={doCreate}>Create Project</button>
        </div>
      </div>
    )
  }

  const [showBranch, setShowBranch] = useState(false)
  const [branchInput, setBranchInput] = useState('')
  const [newBranch, setNewBranch] = useState('')
  const [showDeleteBranch, setShowDeleteBranch] = useState<string | null>(null)
  const switchBranch = () => {
    setBranchInput(status?.current_branch || 'main')
    setNewBranch('')
    setShowBranch(true)
    playSound('click')
  }
  const confirmBranch = async () => {
    const trimmed = branchInput.trim()
    if (!trimmed) return
    setShowBranch(false)
    playSound('click')
    setSyncStep(`Switching to ${trimmed}...`)
    const r = await fetch(`${API}/api/branch`, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({repo, name: trimmed})}).then(r=>r.json())
    if (!r.ok) { playSound('delete'); showInfo('Branch switch failed', r.error, 'error'); setSyncStep(null); return }
    playSound('success'); showToast(`Switched to ${trimmed} ✓`, 'success')
    setSyncStep(`Switched to ${trimmed} ✓`)
    refresh()
    setTimeout(()=>setSyncStep(null), 1200)
  }
  const createBranch = async () => {
    const trimmed = newBranch.trim()
    if (!trimmed) return
    setShowBranch(false)
    playSound('click')
    setSyncStep(`Creating ${trimmed}...`)
    const r = await fetch(`${API}/api/branch`, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({repo, name: trimmed})}).then(r=>r.json())
    if (!r.ok) { playSound('delete'); showInfo('Branch create failed', r.error, 'error'); setSyncStep(null); return }
    playSound('success'); showToast(`Created ${trimmed} ✓`, 'success')
    setSyncStep(`Created ${trimmed} ✓`)
    setNewBranch('')
    refresh()
    setTimeout(()=>setSyncStep(null), 1200)
  }

  return (
    <div className="app">
      <header className="top">
        <div className="brand">
          <img src="/getsyncd-icon.png" alt="Get Syncd" style={{width:32, height:32, borderRadius:8, objectFit:'cover'}} />
          Get Syncd
          <span className="branch" onClick={switchBranch} title="Click to switch or create branch" role="button" tabIndex={0} aria-label={`Switch branch (current: ${status?.current_branch || 'main'})`} onKeyDown={e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();switchBranch()}}} style={{cursor:'pointer'}}>
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M6 3v12"/><circle cx="18" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M18 9a9 9 0 0 1-9 9"/></svg>
  {status?.current_branch || 'main'}
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m6 9 6 6 6-6"/></svg>
</span>
          <span className="branch" onClick={()=>{setShowTimelinePicker(true); playSound('click')}} title="Current timeline — click to switch" role="button" tabIndex={0} aria-label={`Switch timeline (current: ${activeTimeline || status?.current_timeline || 'timeline'})`} onKeyDown={e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();setShowTimelinePicker(true);playSound('click')}}} style={{cursor:'pointer', background: activeTimeline ? 'var(--orange-soft)' : undefined, borderColor: activeTimeline ? 'var(--orange-border)' : undefined, color: activeTimeline ? 'var(--orange)' : undefined}}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="2" y="2" width="20" height="20" rx="2.18"/><line x1="7" y1="2" x2="7" y2="22"/><line x1="17" y1="2" x2="17" y2="22"/><line x1="2" y1="12" x2="22" y2="12"/></svg>
            {activeTimeline || status?.current_timeline || 'timeline'} {status?.timelines?.find(t=>t.name===activeTimeline)?.has_changes ? '•' : ''}
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="m6 9 6 6 6-6"/></svg>
          </span>
        </div>
        <div className="actions">
          {status?.has_changes ? <span className="unsaved" title={status.timelines?.filter(t=>t.has_changes).map(t=>t.name).join(', ') || ''}>● {status.timelines?.filter(t=>t.has_changes).length ? `${status.timelines.filter(t=>t.has_changes).length} timeline${status.timelines.filter(t=>t.has_changes).length>1?'s':''} changed` : 'Unsaved changes'}</span> : <span className="saved">Up to date</span>}
          <button onClick={()=>setShowSave(true)} className="primary">Save {activeTimeline && activeTimeline!=='timeline' ? activeTimeline : 'version'}</button>
          <button onClick={doSync} className="ghost">Sync</button>
        </div>
      </header>

      {syncStep && <div className="syncbar">{syncStep}</div>}

      <div className="tabs">
        <div className="tabList">
          {projects.map(p=>(
            <button key={p.path} className={`tab ${repo===p.path?'active':''}`} onClick={()=>{setRepo(p.path); setSelected(null); setActiveTimeline(null); timelineExplicitlySetRef.current=false; playSound('click')}}>{p.name}</button>
          ))}
          <button className="tab add" onClick={scanResolve} title="Scan DaVinci Resolve library and auto-create folders">+ Scan Resolve</button>
          <button className="tab add" onClick={syncFromResolve} title="Snapshot the currently open Resolve project into this folder (safe, never switches projects)">⇅ Sync Resolve</button>
        </div>
        <span className="tabHint">Auto-creates ~/GetSyncd/&lt;Project&gt; — pick a tab to switch projects</span>
      </div>

      <div className="main">
        <aside className="history">
          <div className="h" style={{display:'flex', justifyContent:'space-between', alignItems:'center'}}>History {activeTimeline && <span style={{fontSize:'10px', background:'var(--orange-soft)', color:'var(--orange)', border:'1px solid var(--orange-border)', padding:'2px 6px', borderRadius:'999px'}}>{activeTimeline}</span>}</div>
          {timelines.length>1 && (
            <div style={{display:'flex', gap:'6px', flexWrap:'wrap', marginBottom:'10px'}}>
              <button onClick={()=>{setActiveTimeline(null); timelineExplicitlySetRef.current=true; playSound('click')}} style={{background: !activeTimeline?'var(--orange)':'transparent', color: !activeTimeline?'white':'var(--muted)', border:'1px solid '+(!activeTimeline?'var(--orange)':'var(--border)'), padding:'4px 8px', borderRadius:'999px', fontSize:'11px', cursor:'pointer'}}>All</button>
              {timelines.map((t)=>(
                <button key={t.name} onClick={()=>{setActiveTimeline(t.name); timelineExplicitlySetRef.current=true; playSound('click')}} style={{background: activeTimeline===t.name?'var(--orange)':'transparent', color: activeTimeline===t.name?'white': t.has_changes?'var(--orange)':'var(--muted)', border:'1px solid '+(activeTimeline===t.name?'var(--orange)': t.has_changes?'var(--orange-border)':'var(--border)'), padding:'4px 8px', borderRadius:'999px', fontSize:'11px', cursor:'pointer', opacity: t.has_changes?1:0.8}}>{t.name} {t.has_changes?'•':''}</button>
              ))}
            </div>
          )}
          {Object.entries(groups).map(([d, vs])=>(
            <div key={d} className="group">
              <div className="gdate">{d}</div>
              {vs.map(v=>(
                <div key={v.hash} className={`row ${selected?.hash===v.hash?'sel':''}`} onClick={()=>setSelected(v)}>
                  <div className="thumb">
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <rect x="2" y="2" width="20" height="20" rx="2.18" ry="2.18"></rect>
    <line x1="7" y1="2" x2="7" y2="22"></line>
    <line x1="17" y1="2" x2="17" y2="22"></line>
    <line x1="2" y1="12" x2="22" y2="12"></line>
    <line x1="2" y1="7" x2="7" y2="7"></line>
    <line x1="2" y1="17" x2="7" y2="17"></line>
    <line x1="17" y1="17" x2="22" y2="17"></line>
    <line x1="17" y1="7" x2="22" y2="7"></line>
  </svg>
</div>
                  <div className="meta">
                    <div className="msg" style={{display:'flex', gap:'6px', alignItems:'center'}}><span style={{flex:1, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap'}}>{v.message}</span>{!activeTimeline && v.timeline && v.timeline!=='timeline' ? <span style={{background:'var(--panel)', border:'1px solid var(--border)', color:'var(--muted)', padding:'1px 5px', borderRadius:'999px', fontSize:'10px', flexShrink:0}}>{v.timeline}</span> : null}</div>
                    <div className="sub">{v.date} • {v.short} {!activeTimeline && v.timeline && v.timeline!=='timeline' ? `• ${v.timeline}` : ''}</div>
                  </div>
                  <button className="delBtn" title="Delete this version" aria-label={`Delete version ${v.short} (${v.message})`} onClick={(e)=>{e.stopPropagation(); doDelete(v)}}>×</button>
                </div>
              ))}
            </div>
          ))}
          {log.length===0 && <div className="empty">No versions yet — Save one above</div>}
        </aside>

        <section className="detail">
          <div className="detailInner">
          {selected ? (
            <>
              <div className="detailHead" style={{flexDirection:'column', alignItems:'center', textAlign:'center'}}>
                <div style={{width:'100%'}}>
                  <h2 style={{textAlign:'center'}}>{selected.message}</h2>
                  <p className="vs" style={{fontWeight:500, color:'var(--text)', textAlign:'center'}}>{diff ? humanSummary(diff.summary) : 'Loading changes...'}</p>
                  <p className="muted" style={{padding:0, fontSize:'12px', marginTop:'4px', textAlign:'center'}}>vs previous • {selected.date} • {selected.short}</p>
                </div>
              </div>
              {diff && <div className="barWrap" style={{width:'100%'}}>
                <div className="bar" style={{width:'100%', height:'36px'}}>
                  {diff.new_track?.items?.slice(0,30).map((it,i:number)=>{
                    const ch = diff.changes?.find(c=>c.index_new===i)
                    const cls = ch ? ch.type : 'unchanged'
                    return <div key={i} className={`clip ${cls}`} title={it.name} />
                  })}
                </div>
                <div className="legend"><span className="l u" /> Unchanged <span className="l t" /> Trimmed <span className="l r" /> Removed <span className="l a" /> Added</div>
              </div>}
              <div className="summaryText">{diff ? humanSummary(diff.summary) : 'Comparing...'}</div>
              <div style={{display:'flex', justifyContent:'flex-start', marginBottom:'16px'}}>
                <button className="ghost" onClick={()=>{playSound('click'); doRestore(selected)}}>Restore</button>
              </div>
              <div className="changes">
                <h3>What changed</h3>
                {diff?.changes?.length ? (showAllChanges ? diff.changes.filter(c=> c.type!=='gap_changed' || !c.clip_name?.startsWith('Gap')) : diff.changes.filter(c=> c.type!=='gap_changed' || !c.clip_name?.startsWith('Gap')).slice(0,10)).map((c,i:number)=>(
                  <div key={i} className={`change ${c.type}`}><span className="dot2" /> <span>{humanChange(c)}</span></div>
                )) : <div className="muted">No clip changes — maybe just a gap or timing tweak</div>}
                {diff?.changes && diff.changes.filter(c=> c.type!=='gap_changed' || !c.clip_name?.startsWith('Gap')).length > 10 && (
                  <button className="ghost" style={{marginTop:'8px'}} onClick={()=>setShowAllChanges(v=>!v)}>{showAllChanges ? 'Show less' : `Show all ${diff.changes.filter(c=> c.type!=='gap_changed' || !c.clip_name?.startsWith('Gap')).length} changes`}</button>
                )}
                {diff && (
                  <div className="notes">
                    {(diff.changes?.filter(c=> c.clip_name?.startsWith('Gap')).length || 0)>0 && (
                      <div className="note gap-note">• {diff.changes?.filter(c=>c.clip_name?.startsWith('Gap')).length} gap{(diff.changes?.filter(c=>c.clip_name?.startsWith('Gap')).length || 0)>1?'s':''} tweaked — usually just spacing, safe to ignore</div>
                    )}
                    {diff?.warnings?.length ? (
                      <div className="note warn-note">⚠ {diff.warnings.map((w:string)=> humanizeWarning(w)).join(' • ')}</div>
                    ) : null}
                  </div>
                )}
              </div>
              <div className="footActions">
                <span className="muted">Project: {repo} — media stays local</span>
              </div>
            </>
          ) : <div className="muted">Select a version on the left</div>}
          </div>
        </section>
        <aside className="gitRail">
          <div className="h" style={{display:'flex', justifyContent:'space-between', alignItems:'center'}}>Git graph <span style={{fontSize:'10px', color:'var(--muted2)', fontWeight:500}}>{graph?.current || status?.current_branch || 'main'} • {graph?.commits?.length||log.length} saves</span></div>
          {(() => {
            const ROW = 80
            const commits: GraphCommit[] = graph?.commits?.length ? graph.commits : log.map((v, i:number)=> ({...v, lane:0, isBranch:false, isFork:false, isCurrent: i===0 && v.hash===log[0]?.hash}))
            const forkHash = graph?.fork
            const altBranch = graph?.altBranch
            // Find fork index
            const forkIdx = forkHash ? commits.findIndex(c=> c.hash===forkHash || c.short===forkHash?.slice(0,8)) : -1
            const hasBranch = altBranch && commits.some(c=>c.isBranch)
            const svgH = Math.max(commits.length * ROW, 200)
            const mainX = 24
            const branchX = 56
            const selectedHash = selected?.hash
            return (
              <div style={{position:'relative', marginTop:'8px'}}>
                <svg width="80" height={svgH} style={{position:'absolute', left:0, top:0, pointerEvents:'none'}}>
                  {/* Main lane */}
                  <line x1={mainX} y1={ROW/2} x2={mainX} y2={svgH - ROW/2} stroke="var(--border2)" strokeWidth={1.25} />
                    {/* Branch lane + S-curve */}
                    {hasBranch && forkIdx >=0 && (
                      <>
                        <line x1={branchX} y1={(forkIdx+1)*ROW + 12} x2={branchX} y2={(commits.findIndex(c=>c.isBranch) !== -1 ? commits.findIndex(c=>c.isBranch) : forkIdx+1)*ROW + ROW/2} stroke="var(--orange)" strokeWidth={1.25} opacity={0.6} />
                      {(() => {
                        const y1 = forkIdx*ROW + ROW/2
                        const y2 = (forkIdx+1)*ROW + 20
                        const midY = (y1 + y2)/2
                        return <path d={`M ${mainX} ${y1} C ${mainX} ${midY}, ${branchX} ${midY}, ${branchX} ${y2}`} fill="none" stroke="var(--orange)" strokeWidth={1.25} opacity={0.6} />
                      })()}
                    </>
                  )}
                  {commits.map((c, i:number)=>{
                    const y = i*ROW + ROW/2
                    const isFork = !!c.isFork
                    const isBranch = !!c.isBranch
                    const isCurrent = !!c.isCurrent
                    const isSelected = !!selectedHash && c.hash===selectedHash
                    const x = isBranch ? branchX : mainX
                    // Selected gets focus ring even if not current, current gets full orange
                    if (isSelected) {
                      return (
                        <g key={c.hash} opacity={1}>
                          <circle cx={x} cy={y} r={14} fill="var(--orange)" opacity={0.12} />
                          <circle cx={x} cy={y} r={9} fill="none" stroke="var(--orange)" strokeWidth={1.25} />
                          <circle cx={x} cy={y} r={4} fill={isBranch ? "var(--orange)" : "white"} stroke={isBranch ? "var(--orange)" : "var(--orange)"} strokeWidth={isBranch?0:1.25} />
                        </g>
                      )
                    }
                    if (isCurrent) {
                      return (
                        <g key={c.hash} opacity={1}>
                          <circle cx={x} cy={y} r={14} fill="var(--orange)" opacity={0.12} />
                          <circle cx={x} cy={y} r={9} fill="none" stroke="var(--orange)" strokeWidth={1.25} />
                          <circle cx={x} cy={y} r={4} fill="var(--orange)" />
                        </g>
                      )
                    }
                    if (isFork) {
                      return <g key={c.hash} opacity={1}><circle cx={x} cy={y} r={7} fill="none" stroke="var(--orange)" strokeWidth={1.25} /><circle cx={x} cy={y} r={3.5} fill="white" /></g>
                    }
                    if (isBranch) {
                      return <circle key={c.hash} cx={x} cy={y} r={5} fill="var(--orange)" opacity={0.6} stroke="var(--orange)" strokeWidth={1.25} />
                    }
                    return <circle key={c.hash} cx={x} cy={y} r={5} fill="var(--border2)" stroke="var(--border2)" strokeWidth={1.25} />
                  })}
                </svg>
                <div style={{marginLeft:'80px'}}>
                  {commits.map((c)=>{
                    const isSelected = !!selectedHash && c.hash===selectedHash
                    const isBranch = !!c.isBranch
                    const isCurrentBranchHead = !!c.isCurrent
                    return (
                    <div key={c.hash} style={{height:ROW, display:'flex', flexDirection:'column', justifyContent:'center', opacity: isSelected?1: (isCurrentBranchHead?1: isBranch?0.6:1)}}>
                      <div style={{fontSize:'14px', fontWeight: isSelected||isCurrentBranchHead?700:600, color: isSelected? 'var(--orange)': c.isCurrent? 'var(--text)': isBranch? 'var(--orange)':'var(--text)', whiteSpace:'nowrap', overflow:'hidden', textOverflow:'ellipsis'}}>{c.message} {isBranch && altBranch ? <span style={{color:'var(--orange)', fontSize:'11px', marginLeft:'6px', opacity: isSelected?1:0.6, fontWeight:600}}>• {altBranch}</span> : null}</div>
                      <div style={{fontSize:'12px', color: isSelected? 'var(--orange)':'var(--muted2)', marginTop:'2px', fontWeight: isSelected?600:400}}>{c.relative || c.date} • {c.short} {isSelected? '• selected' : isCurrentBranchHead? '• current' : ''}</div>
                    </div>
                  )})}
                  {commits.length===0 && <div className="muted" style={{height:ROW, display:'grid', placeItems:'center'}}>No saves yet</div>}
                </div>
              </div>
            )
          })()}
        </aside>
      </div>

      {showSave && (
        <div className="modalBg" onClick={()=>setShowSave(false)}>
          <div className="modal" onClick={e=>e.stopPropagation()}>
            <h3>Save Version</h3>
            <p className="muted">This will create a new version from {repo}/timeline.otio</p>
            <textarea value={note} onChange={e=>setNote(e.target.value)} placeholder="Audio cleanup — trimmed intro, added B-roll" rows={3} />
            <div className="modalActions">
              <button onClick={()=>setShowSave(false)}>Cancel</button>
              <button className="primary" onClick={doSave}>Save Version</button>
            </div>
          </div>
        </div>
      )}
      {showRestore && (
        <div className="modalBg" onClick={()=>setShowRestore(null)}>
          <div className="modal" onClick={e=>e.stopPropagation()}>
            <h3>Restore version?</h3>
            <p><b>{showRestore.message}</b> <span className="muted">• {showRestore.short} • {showRestore.date}</span></p>
            <p className="muted">This will overwrite <code>{repo}/timeline.otio</code> with this version. {status?.has_changes ? "A safety snapshot will be saved first." : "You can go back by restoring the latest again."}</p>
            <div className="modalActions">
              <button onClick={()=>setShowRestore(null)}>Go back</button>
              <button className="primary" onClick={confirmRestore}>Restore</button>
            </div>
          </div>
        </div>
      )}
      {showDelete && (
        <div className="modalBg" onClick={()=>setShowDelete(null)}>
          <div className="modal" onClick={e=>e.stopPropagation()}>
            <h3>Delete version?</h3>
            <p><b>{showDelete.message}</b> <span className="muted">• {showDelete.short} • {showDelete.date}</span></p>
            <p className="muted">This will permanently remove this version from history. Later versions will get new IDs. Cannot be undone without a backup.</p>
            <div className="modalActions">
              <button onClick={()=>setShowDelete(null)}>Go back</button>
              <button className="primary" style={{background:'var(--red)', color:'white'}} onClick={confirmDelete}>Delete</button>
            </div>
          </div>
        </div>
      )}
      {showBranch && !showDeleteBranch && (
        <div className="modalBg" onClick={()=>setShowBranch(false)}>
          <div className="modal" onClick={e=>e.stopPropagation()} style={{maxWidth:'420px'}}>
            <h3>Branches</h3>
            <p className="muted" style={{marginBottom:'14px'}}>Current <b style={{color:'var(--text)'}}>{status?.current_branch || 'main'}</b> • {status?.branches?.length||1} total</p>
            <div style={{display:'flex', gap:'8px', marginBottom:'16px'}}>
              <select value={branchInput} onChange={e=>setBranchInput(e.target.value)} style={{flex:1, background:'var(--bg)', border:'1px solid var(--border)', color:'var(--text)', padding:'9px 12px', borderRadius:'var(--radius-card)', fontSize:'13px'}}>
                {(status?.branches||['main']).map(b=><option key={b} value={b}>{b}{b===status?.current_branch?' — current':''}</option>)}
              </select>
              <button className="primary" onClick={confirmBranch}>Switch</button>
            </div>
            <div style={{display:'flex', gap:'8px', marginBottom:'14px'}}>
              <input value={newBranch} onChange={e=>setNewBranch(e.target.value)} placeholder="new-branch name" style={{flex:1, background:'var(--bg)', border:'1px solid var(--border)', color:'var(--text)', padding:'9px 12px', borderRadius:'var(--radius-card)', fontSize:'13px'}} onKeyDown={e=>e.key==='Enter'&&createBranch()} />
              <button className="ghost" onClick={createBranch}>Create</button>
            </div>
            {(status?.branches||[]).filter(b=>b!==status?.current_branch).length>0 && (
              <div style={{borderTop:'1px solid var(--border)', paddingTop:'12px'}}>
                <div style={{fontSize:'11px', color:'var(--muted2)', marginBottom:'8px', fontWeight:600}}>Delete</div>
                <div style={{display:'flex', flexWrap:'wrap', gap:'6px'}}>
                  {(status?.branches||[]).filter(b=>b!==status?.current_branch).map(b=>(
                    <button key={b} onClick={()=>setShowDeleteBranch(b)} style={{background:'transparent', border:'1px solid var(--border)', color:'var(--muted)', padding:'5px 10px', borderRadius:'var(--radius-pill)', fontSize:'12px', cursor:'pointer'}}>{b} ×</button>
                  ))}
                </div>
              </div>
            )}
            <div className="modalActions" style={{marginTop:'16px'}}>
              <button onClick={()=>setShowBranch(false)}>Close</button>
            </div>
          </div>
        </div>
      )}
      {showDeleteBranch && !pendingForceDelete && (
        <div className="modalBg" onClick={()=>setShowDeleteBranch(null)}>
          <div className="modal" onClick={e=>e.stopPropagation()}>
            <h3>Delete branch “{showDeleteBranch}”?</h3>
            <p className="muted">This removes the branch pointer. Commits stay in other branches, but if “{showDeleteBranch}” isn’t merged into “{status?.current_branch}”, those commits become orphaned. You can’t undo without <code>git reflog</code>.</p>
            <p className="muted" style={{fontSize:'12px', marginTop:'8px', color:'var(--red)'}}>This only deletes the branch, not the project folder or timeline file.</p>
            <div className="modalActions">
              <button onClick={()=>setShowDeleteBranch(null)}>Go back</button>
              <button className="primary" style={{background:'var(--red)', borderColor:'var(--red)'}} onClick={async()=>{
                const b = showDeleteBranch
                setShowDeleteBranch(null)
                setShowBranch(false)
                playSound('delete')
                const r = await fetch(`${API}/api/branch/delete`, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({repo, name:b, force:false})}).then(r=>r.json())
                if (!r.ok) {
                  if (typeof r.error === 'string' && r.error.includes('not fully merged')) {
                    setSyncStep(null)
                    setPendingForceDelete(b)
                    return
                  } else { showInfo('Delete branch failed', r.error, 'error'); setSyncStep(null); return }
                }
                showToast(`Deleted branch ${b}`, 'success')
                refresh()
              }}>Delete branch</button>
            </div>
          </div>
        </div>
      )}
      {pendingForceDelete && (
        <div className="modalBg" onClick={()=>setPendingForceDelete(null)}>
          <div className="modal" onClick={e=>e.stopPropagation()}>
            <h3>Force delete “{pendingForceDelete}”?</h3>
            <p className="muted">Branch “{pendingForceDelete}” is not fully merged — force delete will orphan its commits. This cannot be undone without <code>git reflog</code>.</p>
            <div className="modalActions">
              <button onClick={()=>setPendingForceDelete(null)}>Go back</button>
              <button className="primary" style={{background:'var(--red)', borderColor:'var(--red)'}} onClick={async()=>{
                const b = pendingForceDelete
                setPendingForceDelete(null)
                playSound('delete')
                const r2 = await fetch(`${API}/api/branch/delete`, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({repo, name:b, force:true})}).then(r=>r.json())
                if (!r2.ok) { showInfo('Force delete failed', r2.error, 'error'); setSyncStep(null); return }
                showToast(`Deleted branch ${b}`, 'success')
                refresh()
              }}>Force delete</button>
            </div>
          </div>
        </div>
      )}
      {infoModal && (
        <div className="modalBg" onClick={()=>setInfoModal(null)}>
          <div className="modal" onClick={e=>e.stopPropagation()}>
            <h3>{infoModal.title}</h3>
            <p className="muted" style={{whiteSpace:'pre-wrap'}}>{infoModal.body}</p>
            <div className="modalActions">
              <button className="primary" onClick={()=>setInfoModal(null)}>OK</button>
            </div>
          </div>
        </div>
      )}
      {showTimelinePicker && (
        <div className="modalBg" onClick={()=>setShowTimelinePicker(false)}>
          <div className="modal" onClick={e=>e.stopPropagation()}>
            <h3>Timelines — {activeTimeline || 'All'}</h3>
            <p className="muted">You’re working on <b style={{color:'var(--text)'}}>{status?.current_timeline || activeTimeline || 'timeline'}</b> in Resolve. Pick which timeline’s history to show.</p>
            <div style={{display:'flex', flexDirection:'column', gap:'8px', marginTop:'14px', maxHeight:'280px', overflow:'auto'}}>
              <button onClick={()=>{setActiveTimeline(null); timelineExplicitlySetRef.current=true; setShowTimelinePicker(false); playSound('click')}} style={{textAlign:'left', padding:'10px 12px', borderRadius:'var(--radius-card)', border: !activeTimeline?'1px solid var(--orange)':'1px solid var(--border)', background: !activeTimeline?'var(--orange-soft)':'var(--panel2)', color: !activeTimeline?'var(--orange)':'var(--text)', fontWeight: !activeTimeline?700:500, cursor:'pointer'}}>All timelines • {timelines.length} total</button>
              {timelines.map((t)=>(
                <button key={t.name} onClick={()=>{setActiveTimeline(t.name); timelineExplicitlySetRef.current=true; setShowTimelinePicker(false); playSound('click')}} style={{textAlign:'left', padding:'10px 12px', borderRadius:'var(--radius-card)', border: activeTimeline===t.name?'1px solid var(--orange)':'1px solid var(--border)', background: activeTimeline===t.name?'var(--orange-soft)': t.has_changes?'var(--yellow-soft)':'var(--panel2)', color: activeTimeline===t.name?'var(--orange)': t.has_changes?'var(--yellow)':'var(--text)', display:'flex', justifyContent:'space-between', alignItems:'center', cursor:'pointer'}}>
                  <span style={{fontWeight: activeTimeline===t.name?700:500}}>{t.name} {t.name===status?.current_timeline?'• current':''}</span>
                  <span style={{fontSize:'11px', color: t.has_changes?'var(--orange)':'var(--muted)', background: t.has_changes?'var(--orange-soft)':'transparent', padding: t.has_changes?'2px 6px':'0', borderRadius:'999px'}}>{t.has_changes ? '• unsaved' : t.message?.includes('Not yet') ? 'not exported' : 'up to date'}</span>
                </button>
              ))}
              {timelines.length===0 && <div className="muted">No timelines yet — export one from Resolve to timelines/NAME.otio</div>}
            </div>
            <div className="modalActions">
              <button onClick={()=>setShowTimelinePicker(false)}>Close</button>
            </div>
          </div>
        </div>
      )}
      {toast && <div className={`toast ${toast.type} show`}>{toast.msg}</div>}
    </div>
  )
}

function FirstRunWizard(props: {
  defaultRepo: string
  api: (path: string, opts?: RequestInit) => Promise<any>
  notify: (title: string, body: string, type?: 'success'|'error'|'info') => void
  click: (type?: 'click'|'success'|'delete'|'pop') => void
  onDismiss: () => void
  onDone: (path: string) => void
}) {
  const { defaultRepo, api, notify, click, onDismiss, onDone } = props
  const [step, setStep] = useState(0)
  const [resolveInfo, setResolveInfo] = useState<{project: string|null, current_timeline: string|null, timelines: string[]}|null>(null)
  const [checking, setChecking] = useState(false)
  const [projName, setProjName] = useState('')
  const [busy, setBusy] = useState(false)
  const [createdPath, setCreatedPath] = useState<string|null>(null)
  const [ghStatus, setGhStatus] = useState<{ok?:boolean; has_gh?:boolean; authed?:boolean; error?:string}|null>(null)
  const [ghName, setGhName] = useState('')
  const [ghPrivate, setGhPrivate] = useState(true)
  const [ghUrl, setGhUrl] = useState<string|null>(null)

  const checkResolve = async () => {
    setChecking(true)
    try {
      const r = await fetch(`${API}/api/resolve/current`).then(x=>x.json())
      setResolveInfo({project: r.project || null, current_timeline: r.current_timeline || null, timelines: r.timelines || []})
      if (r.project && !projName) setProjName(r.project)
    } catch {
      setResolveInfo({project: null, current_timeline: null, timelines: []})
    } finally {
      setChecking(false)
    }
  }
  useEffect(()=>{ checkResolve() }, [])

  const loadGh = async () => {
    try {
      const r = await fetch(`${API}/api/github/status`).then(x=>x.json())
      setGhStatus(r)
    } catch {
      setGhStatus({ok:false, has_gh:false, authed:false, error:'Could not reach the sidecar.'})
    }
  }
  useEffect(()=>{ if (step===3) loadGh() }, [step])

  const createProject = async () => {
    const name = projName.trim()
    if (!name) { notify('Name required', 'Give your project a name first.', 'error'); return }
    setBusy(true)
    try {
      const target = `${defaultRepo}/${name}`
      await api('/api/init', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({repo: target})})
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
      const r = await api('/api/github/create', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({repo: createdPath, name: ghName.trim(), private: ghPrivate})}) as {ok?:boolean; url?:string}
      if (r.url) setGhUrl(r.url)
      click('success')
    } catch (e) {
      notify('GitHub create failed', e instanceof Error ? e.message : 'Could not create repo.', 'error')
    } finally {
      setBusy(false)
    }
  }

  const go = (n:number) => { click('click'); setStep(n) }
  const targetPreview = projName.trim() ? `${defaultRepo}/${projName.trim()}` : `${defaultRepo}/MyProject`

  return (
    <div className="setup">
      <h1>Get Syncd</h1>
      <div className="card" style={{maxWidth:'520px'}}>
        <div className="muted" style={{fontSize:'12px', marginBottom:'12px'}}>Step {step+1} of 5 {createdPath ? `• ${createdPath}` : ''}</div>
        {step===0 && (
          <>
            <h3>Version control for your edits</h3>
            <p className="muted">Every save is a checkpoint of your timeline — see what changed in plain English and jump back to any cut. Your <b style={{color:'var(--text)'}}>media never leaves this computer</b>; only the tiny timeline file is versioned.</p>
            <div className="modalActions">
              <button className="ghost" onClick={()=>{click('click'); onDismiss()}}>Skip setup</button>
              <button className="primary big" onClick={()=>go(1)}>Get started</button>
            </div>
          </>
        )}
        {step===1 && (
          <>
            <h3>Find DaVinci Resolve</h3>
            {checking && <p className="muted">Checking for a running Resolve…</p>}
            {!checking && resolveInfo?.project && (
              <p>Found project <b style={{color:'var(--text)'}}>{resolveInfo.project}</b>{resolveInfo.current_timeline ? ` • timeline ${resolveInfo.current_timeline}` : ''} ({resolveInfo.timelines.length} timeline{resolveInfo.timelines.length===1?'':'s'}).</p>
            )}
            {!checking && !resolveInfo?.project && (
              <p className="muted">Resolve isn't reachable. Open Resolve with a project, enable Preferences → System → General → External scripting, then check again. You can also continue without it.</p>
            )}
            <div className="modalActions">
              <button className="ghost" onClick={()=>go(0)}>Back</button>
              <button className="ghost" onClick={()=>{checkResolve()}}>Check again</button>
              <button className="primary" onClick={()=>go(2)}>Continue</button>
            </div>
          </>
        )}
        {step===2 && (
          <>
            <h3>Create your first project</h3>
            <p className="muted">This creates a folder with its own git history.</p>
            <label>Project name:</label>
            <div className="row">
              <input value={projName} onChange={e=>setProjName(e.target.value)} placeholder={resolveInfo?.project || 'MyProject'} onKeyDown={e=>{if(e.key==='Enter') createProject()}} />
            </div>
            <p className="muted" style={{fontSize:'12px'}}>Folder: <code>{targetPreview}</code></p>
            <div className="modalActions">
              <button className="ghost" onClick={()=>go(1)}>Back</button>
              <button className="primary" disabled={busy} onClick={createProject}>{busy ? 'Creating…' : 'Create project'}</button>
            </div>
          </>
        )}
        {step===3 && (
          <>
            <h3>Back up to GitHub? (optional)</h3>
            {!ghStatus && <p className="muted">Checking GitHub CLI…</p>}
            {ghStatus && (!ghStatus.has_gh || !ghStatus.authed) && (
              <p className="muted">{ghStatus.error} You can do this later with <code>gh auth login</code> — local saves work fully offline either way.</p>
            )}
            {ghStatus?.ok && !ghUrl && (
              <>
                <label>Repository name:</label>
                <div className="row">
                  <input value={ghName} onChange={e=>setGhName(e.target.value)} placeholder="my-film" />
                </div>
                <label style={{display:'flex', gap:'8px', alignItems:'center', marginTop:'8px'}}>
                  <input type="checkbox" checked={ghPrivate} onChange={e=>setGhPrivate(e.target.checked)} /> Private repository
                </label>
              </>
            )}
            {ghUrl && <p>Created: <b style={{color:'var(--text)'}}>{ghUrl}</b> — pushed ✓</p>}
            <div className="modalActions">
              <button className="ghost" onClick={()=>go(2)}>Back</button>
              {ghStatus?.ok && !ghUrl && <button className="primary" disabled={busy || !ghName.trim()} onClick={createGithub}>{busy ? 'Creating…' : 'Create & push'}</button>}
              <button className={ghStatus?.ok && !ghUrl ? 'ghost' : 'primary'} onClick={()=>go(4)}>{ghUrl || !ghStatus?.ok ? 'Continue' : 'Skip'}</button>
            </div>
          </>
        )}
        {step===4 && (
          <>
            <h3>Where things live</h3>
            <div className="detect">
              <div>Project: <b>{createdPath || targetPreview}</b></div>
              <div>Timeline: <b>auto-exported on every Save</b></div>
              <div>Media: <b>stays local, never uploaded</b></div>
              <p className="muted">Only the small timeline file is versioned. Media paths are absolute — if you move drives, relink in Resolve's Media Pool as usual.</p>
            </div>
            <div className="modalActions">
              <button className="ghost" onClick={()=>go(3)}>Back</button>
              <button className="primary big" onClick={()=>{click('success'); onDone(createdPath || targetPreview)}}>Open Get Syncd</button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
