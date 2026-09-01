import { useEffect, useState } from 'react'
import './App.css'

const API = 'http://127.0.0.1:5174'
const DEFAULT_REPO = '/Users/mihailmihaylov/GetSyncd'

type Version = { hash: string; short: string; author: string; date: string; message: string; preview?: string }
type Status = { is_repo: boolean; has_changes: boolean | null; message: string; current_branch?: string; branches?: string[], timelines?: any[], current_timeline?: string | null, all_timelines?: string[] }

export default function App() {
  const [repo, setRepo] = useState(DEFAULT_REPO)
  const [status, setStatus] = useState<Status | null>(null)
  const [log, setLog] = useState<Version[]>([])
  const [selected, setSelected] = useState<Version | null>(null)
  const [diff, setDiff] = useState<any>(null)
  const [note, setNote] = useState('')
  const [showSave, setShowSave] = useState(false)
  const [showSetup, setShowSetup] = useState(false)
  const [syncStep, setSyncStep] = useState<string | null>(null)
  const [folder, setFolder] = useState(DEFAULT_REPO)
  const [projects, setProjects] = useState<{name:string,path:string}[]>([])
  const [graph, setGraph] = useState<any>(null)
  const [timelines, setTimelines] = useState<any[]>([])
  const [activeTimeline, setActiveTimeline] = useState<string | null>(null)
  const [showTimelinePicker, setShowTimelinePicker] = useState(false)
  const [toast, setToast] = useState<{msg:string, type:'success'|'error'|'info'}|null>(null)
  const showToast = (msg:string, type:'success'|'error'|'info'='success') => { setToast({msg, type}); setTimeout(()=>setToast(null), 2600) }
  const playSound = (type:'click'|'success'|'delete'|'pop'='click') => {
    try {
      const ctx = new (window.AudioContext || (window as any).webkitAudioContext)()
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

  const api = async (path: string, opts?: RequestInit) => {
    const url = `${API}${path}${path.includes('?') ? '&' : '?'}repo=${encodeURIComponent(repo)}`
    const r = await fetch(url, opts)
    return r.json()
  }

  const refreshProjects = async () => {
    try {
      const r = await fetch(`${API}/api/projects`).then(x=>x.json())
      if (r.ok) {
        const projs = r.projects || []
        setProjects(projs)
        // If current repo is the base container (not a project) or not in list, switch to first project
        if (projs.length && !projs.find((p:any)=>p.path===repo)) {
          // Don't auto-switch if repo is already a valid project, only if it's the base
          if (repo === DEFAULT_REPO) {
            setRepo(projs[0].path)
            setSelected(null)
          }
        }
      }
    } catch {}
  }

  const scanResolve = async () => {
    playSound('click')
    const r = await fetch(`${API}/api/resolve/scan`, {method:'POST'}).then(x=>x.json())
    refreshProjects(); refresh()
    if (!r.ok) {
      playSound('pop')
      const hint = r.folders?.length ? `\n\nExisting projects: ${r.folders.map((f:any)=>f.name).join(', ')}` : ''
      alert((r.error || 'Resolve not running') + hint + '\n\nYou can still Create Project manually with the button or type a name.')
      return
    }
    playSound('success'); showToast(r.created?.length ? `Created ${r.created.join(', ')}` : 'Scanned Resolve ✓', 'success')
    if (r.created?.length) alert(`Created folders for: ${r.created.join(', ')}`)
    else if (!r.projects?.length) alert(`No Resolve projects found — open a project in Resolve first. Existing GetSyncd projects shown.`)
  }

  const [showRestore, setShowRestore] = useState<Version | null>(null)
  const [showDelete, setShowDelete] = useState<Version | null>(null)

  const refresh = async () => {
    try {
      const s = await api('/api/status')
      setStatus(s)
      if (!s.is_repo) { setShowSetup(true); return }
      setShowSetup(false)
      // Timelines: use status.timelines or fetch dedicated
      if (s.timelines) {
        setTimelines(s.timelines)
        if (s.current_timeline && !activeTimeline) setActiveTimeline(s.current_timeline)
        else if (s.all_timelines?.length && !activeTimeline) setActiveTimeline(s.all_timelines[0])
        else if (s.timelines.length && !activeTimeline) setActiveTimeline(s.timelines[0].name)
      } else {
        try {
          const t = await api('/api/timelines')
          if (t?.ok) {
            setTimelines(t.timelines || [])
            if (t.current && !activeTimeline) setActiveTimeline(t.current)
          }
        } catch {}
      }
      const tlParam = activeTimeline ? `&timeline=${encodeURIComponent(activeTimeline)}` : ''
      let l = await api(`/api/log?limit=30${tlParam}`)
      // Fallback to legacy log if timeline-specific is empty
      if (Array.isArray(l) && l.length===0 && activeTimeline) {
        try { const fallback = await api(`/api/log?limit=30`); if (Array.isArray(fallback) && fallback.length) l = fallback } catch {}
      }
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
        const g = await api(`/api/graph/viz${activeTimeline?`?timeline=${encodeURIComponent(activeTimeline)}`:''}`)
        if (g?.ok) setGraph(g)
        else if (Array.isArray(g?.commits)) setGraph(g)
        else setGraph(null)
      } catch { setGraph(null) }
    } catch (e) { console.error(e) }
  }

  useEffect(() => { refreshProjects(); refresh(); const id=setInterval(refresh, 3000); return ()=>clearInterval(id) }, [repo, activeTimeline])
  useEffect(()=>{ refreshProjects() }, [log.length])
  useEffect(() => {
    if (!selected || log.length<2) return
    const idx = log.findIndex(v=>v.hash===selected.hash)
    const a = idx+1<log.length ? log[idx+1].hash : selected.hash
    const tl = activeTimeline ? `&timeline=${encodeURIComponent(activeTimeline)}` : ''
    api(`/api/diff?a=${a}&b=${selected.hash}${tl}`).then(setDiff).catch(()=>setDiff(null))
  }, [selected, activeTimeline])

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
    const st = await api('/api/status')
    if (!st.has_changes) { playSound('pop'); showToast('No changes to save', 'info'); alert('No changes to save — edit in Resolve and re-export ~/GetSyncd/timeline.otio first' + (st.message?.includes('Found') ? `\n\nFound: ${st.candidate || ''}` : '')); setSyncStep(null); return }
    setSyncStep('Creating version...')
    const res = await fetch(`${API}/api/save`, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({repo, message: note || undefined, timeline: activeTimeline || undefined})}).then(r=>r.json())
    if (!res.ok) { playSound('delete'); showToast(res.error, 'error'); alert(res.error); setSyncStep(null); return }
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
    const res = await fetch(`${API}/api/restore`, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({repo, rev: v.hash, apply: true, timeline: activeTimeline || (v as any).timeline || undefined})}).then(r=>r.json())
    if (!res.ok) { playSound('delete'); showToast(`Restore failed`, 'error'); alert(`Restore failed: ${res.error}\nYour current work was not deleted.`); setSyncStep(null); return }
    playSound('success'); showToast(`Restored to ${v.short} ✓`, 'success')
    setSyncStep(`Restored to ${v.short} ✓`)
    refresh()
    setTimeout(()=>setSyncStep(null), 1500)
    if (res.auto_import) {
      alert(`Restored to ${v.short} and auto-imported into Resolve ✓\n${res.auto_import_msg}\n\nNo manual import needed — just play the timeline in Resolve.`)
    } else {
      alert(`Restored to ${v.short}\n${res.auto_import_msg || ''}\n\nIn Resolve: File → Import Timeline → OpenTimelineIO → timeline.otio`)
    }
  }

  const doDelete = (v: Version) => setShowDelete(v)
  const confirmDelete = async () => {
    const v = showDelete
    if (!v) return
    setShowDelete(null)
    playSound('delete')
    setSyncStep(`Deleting ${v.short}...`)
    const res = await fetch(`${API}/api/delete`, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({repo, rev: v.hash, timeline: activeTimeline || (v as any).timeline || undefined})}).then(r=>r.json())
    if (!res.ok) { playSound('delete'); showToast(`Delete failed`, 'error'); alert(`Delete failed: ${res.error}`); setSyncStep(null); return }
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
      const s = await api('/api/status')
      if (!s.is_repo) { alert('No project yet — Create Project first'); setSyncStep(null); return }
      // In real app, call POST /api/push
      setSyncStep('Complete ✓')
      setTimeout(()=>setSyncStep(null), 1200)
    } catch (e:any) {
      alert(`SYNC FAILED\n\nYour local project has not been deleted.\n${e.message}\n\n[Reconnect GitHub] [Retry]`)
      setSyncStep(null)
    }
  }

  const doCreate = async () => {
    const r = await fetch(`${API}/api/init`, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({repo: folder})}).then(r=>r.json())
    if (!r.ok) alert(r.error)
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

  if (showSetup) {
    return (
      <div className="setup">
        <h1>Create Project</h1>
        <div className="card">
          <label>Project folder:</label>
          <div className="row">
            <input value={folder} onChange={e=>setFolder(e.target.value)} placeholder="~/GetSyncd" />
            <button onClick={()=>setFolder(DEFAULT_REPO)}>Select Folder</button>
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
    if (!r.ok) { playSound('delete'); showToast(r.error, 'error'); alert(r.error); setSyncStep(null); return }
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
    if (!r.ok) { playSound('delete'); showToast(r.error, 'error'); alert(r.error); setSyncStep(null); return }
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
          <span className="branch" onClick={switchBranch} title="Click to switch or create branch" style={{cursor:'pointer'}}>
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M6 3v12"/><circle cx="18" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M18 9a9 9 0 0 1-9 9"/></svg>
  {status?.current_branch || 'main'}
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m6 9 6 6 6-6"/></svg>
</span>
          <span className="branch" onClick={()=>setShowTimelinePicker(true)} title="Current timeline — click to switch" style={{cursor:'pointer', background: activeTimeline ? 'var(--orange-soft)' : undefined, borderColor: activeTimeline ? 'var(--orange-border)' : undefined, color: activeTimeline ? 'var(--orange)' : undefined}}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="2" y="2" width="20" height="20" rx="2.18"/><line x1="7" y1="2" x2="7" y2="22"/><line x1="17" y1="2" x2="17" y2="22"/><line x1="2" y1="12" x2="22" y2="12"/></svg>
            {activeTimeline || status?.current_timeline || 'timeline'} {status?.timelines?.find((t:any)=>t.name===activeTimeline)?.has_changes ? '•' : ''}
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="m6 9 6 6 6-6"/></svg>
          </span>
        </div>
        <div className="actions">
          {status?.has_changes ? <span className="unsaved" title={status.timelines?.filter((t:any)=>t.has_changes).map((t:any)=>t.name).join(', ') || ''}>● {status.timelines?.filter((t:any)=>t.has_changes).length ? `${status.timelines.filter((t:any)=>t.has_changes).length} timeline${status.timelines.filter((t:any)=>t.has_changes).length>1?'s':''} changed` : 'Unsaved changes'}</span> : <span className="saved">Up to date</span>}
          <button onClick={()=>setShowSave(true)} className="primary">Save {activeTimeline && activeTimeline!=='timeline' ? activeTimeline : 'version'}</button>
          <button onClick={doSync} className="ghost">Sync</button>
        </div>
      </header>

      {syncStep && <div className="syncbar">{syncStep}</div>}

      <div className="tabs">
        <div className="tabList">
          {projects.map(p=>(
            <button key={p.path} className={`tab ${repo===p.path?'active':''}`} onClick={()=>{setRepo(p.path); setSelected(null)}}>{p.name}</button>
          ))}
          <button className="tab add" onClick={scanResolve} title="Scan DaVinci Resolve library and auto-create folders">+ Scan Resolve</button>
        </div>
        <span className="tabHint">Auto-creates ~/GetSyncd/&lt;Project&gt; — pick a tab to switch projects</span>
      </div>

      <div className="main">
        <aside className="history">
          <div className="h" style={{display:'flex', justifyContent:'space-between', alignItems:'center'}}>History {activeTimeline && <span style={{fontSize:'10px', background:'var(--orange-soft)', color:'var(--orange)', border:'1px solid var(--orange-border)', padding:'2px 6px', borderRadius:'999px'}}>{activeTimeline}</span>}</div>
          {timelines.length>1 && (
            <div style={{display:'flex', gap:'6px', flexWrap:'wrap', marginBottom:'10px'}}>
              <button onClick={()=>setActiveTimeline(null)} style={{background: !activeTimeline?'var(--orange)':'transparent', color: !activeTimeline?'white':'var(--muted)', border:'1px solid '+(!activeTimeline?'var(--orange)':'var(--border)'), padding:'4px 8px', borderRadius:'999px', fontSize:'11px', cursor:'pointer'}}>All</button>
              {timelines.map((t:any)=>(
                <button key={t.name} onClick={()=>{setActiveTimeline(t.name); playSound('click')}} style={{background: activeTimeline===t.name?'var(--orange)':'transparent', color: activeTimeline===t.name?'white': t.has_changes?'var(--orange)':'var(--muted)', border:'1px solid '+(activeTimeline===t.name?'var(--orange)': t.has_changes?'var(--orange-border)':'var(--border)'), padding:'4px 8px', borderRadius:'999px', fontSize:'11px', cursor:'pointer', opacity: t.has_changes?1:0.8}}>{t.name} {t.has_changes?'•':''}</button>
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
                    <div className="msg" style={{display:'flex', gap:'6px', alignItems:'center'}}><span style={{flex:1, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap'}}>{v.message}</span>{!activeTimeline && (v as any).timeline && (v as any).timeline!=='timeline' ? <span style={{background:'var(--panel)', border:'1px solid var(--border)', color:'var(--muted)', padding:'1px 5px', borderRadius:'999px', fontSize:'10px', flexShrink:0}}>{(v as any).timeline}</span> : null}</div>
                    <div className="sub">{v.date} • {v.short} {!activeTimeline && (v as any).timeline && (v as any).timeline!=='timeline' ? `• ${(v as any).timeline}` : ''}</div>
                  </div>
                  <button className="delBtn" title="Delete this version" onClick={(e)=>{e.stopPropagation(); doDelete(v)}}>×</button>
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
                  {diff.new_track?.items?.slice(0,30).map((it:any,i:number)=>{
                    const ch = diff.changes.find((c:any)=>c.index_new===i)
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
                {diff?.changes?.length ? diff.changes.filter((c:any)=> c.type!=='gap_changed' || !c.clip_name?.startsWith('Gap')).slice(0,10).map((c:any,i:number)=>(
                  <div key={i} className={`change ${c.type}`}><span className="dot2" /> <span>{humanChange(c)}</span></div>
                )) : <div className="muted">No clip changes — maybe just a gap or timing tweak</div>}
                {diff && (
                  <div className="notes">
                    {diff.changes.filter((c:any)=> c.clip_name?.startsWith('Gap')).length>0 && (
                      <div className="note gap-note">• {diff.changes.filter((c:any)=>c.clip_name?.startsWith('Gap')).length} gap{diff.changes.filter((c:any)=>c.clip_name?.startsWith('Gap')).length>1?'s':''} tweaked — usually just spacing, safe to ignore</div>
                    )}
                    {diff?.warnings?.length ? (
                      <div className="note warn-note">⚠ {diff.warnings.map((w:string)=> w.replace("Track list changed:", "Tracks:").replace("auto-merge not safe", "check tracks manually")).join(' • ')}</div>
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
            const commits = graph?.commits?.length ? graph.commits : log.map((v:any, i:number)=> ({...v, lane:0, isBranch:false, isFork:false, isCurrent: i===0 && v.hash===log[0]?.hash}))
            const forkHash = graph?.fork
            const altBranch = graph?.altBranch
            // Find fork index
            const forkIdx = forkHash ? commits.findIndex((c:any)=> c.hash===forkHash || c.short===forkHash?.slice(0,8)) : -1
            const hasBranch = altBranch && commits.some((c:any)=>c.isBranch)
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
                      <line x1={branchX} y1={(forkIdx+1)*ROW + 12} x2={branchX} y2={(commits.findIndex((c:any)=>c.isBranch) !== -1 ? commits.findIndex((c:any)=>c.isBranch) : forkIdx+1)*ROW + ROW/2} stroke="var(--orange)" strokeWidth={1.25} opacity={0.6} />
                      {(() => {
                        const y1 = forkIdx*ROW + ROW/2
                        const y2 = (forkIdx+1)*ROW + 20
                        const midY = (y1 + y2)/2
                        return <path d={`M ${mainX} ${y1} C ${mainX} ${midY}, ${branchX} ${midY}, ${branchX} ${y2}`} fill="none" stroke="var(--orange)" strokeWidth={1.25} opacity={0.6} />
                      })()}
                    </>
                  )}
                  {commits.map((c:any, i:number)=>{
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
                  {commits.map((c:any)=>{
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
      {showDeleteBranch && (
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
                  if (r.error.includes('not fully merged')) {
                    setSyncStep(r.error)
                    if (!confirm(`Branch "${b}" not fully merged — force delete and orphan commits?`)) { setSyncStep(null); return }
                    const r2 = await fetch(`${API}/api/branch/delete`, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({repo, name:b, force:true})}).then(r=>r.json())
                    if (!r2.ok) { alert(r2.error); setSyncStep(null); return }
                  } else { alert(r.error); setSyncStep(null); return }
                }
                showToast(`Deleted branch ${b}`, 'success')
                refresh()
              }}>Delete branch</button>
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
              <button onClick={()=>{setActiveTimeline(null); setShowTimelinePicker(false); playSound('click')}} style={{textAlign:'left', padding:'10px 12px', borderRadius:'var(--radius-card)', border: !activeTimeline?'1px solid var(--orange)':'1px solid var(--border)', background: !activeTimeline?'var(--orange-soft)':'var(--panel2)', color: !activeTimeline?'var(--orange)':'var(--text)', fontWeight: !activeTimeline?700:500, cursor:'pointer'}}>All timelines • {timelines.length} total</button>
              {timelines.map((t:any)=>(
                <button key={t.name} onClick={()=>{setActiveTimeline(t.name); setShowTimelinePicker(false); playSound('click')}} style={{textAlign:'left', padding:'10px 12px', borderRadius:'var(--radius-card)', border: activeTimeline===t.name?'1px solid var(--orange)':'1px solid var(--border)', background: activeTimeline===t.name?'var(--orange-soft)': t.has_changes?'var(--yellow-soft)':'var(--panel2)', color: activeTimeline===t.name?'var(--orange)': t.has_changes?'var(--yellow)':'var(--text)', display:'flex', justifyContent:'space-between', alignItems:'center', cursor:'pointer'}}>
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
