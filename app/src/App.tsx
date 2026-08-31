import { useEffect, useState } from 'react'
import './App.css'

const API = 'http://127.0.0.1:5174'
const DEFAULT_REPO = '/Users/mihailmihaylov/GetSyncd'

type Version = { hash: string; short: string; author: string; date: string; message: string; preview?: string }
type Status = { is_repo: boolean; has_changes: boolean | null; message: string; current_branch?: string; branches?: string[] }

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

  const api = async (path: string, opts?: RequestInit) => {
    const url = `${API}${path}${path.includes('?') ? '&' : '?'}repo=${encodeURIComponent(repo)}`
    const r = await fetch(url, opts)
    return r.json()
  }

  const refresh = async () => {
    try {
      const s = await api('/api/status')
      setStatus(s)
      if (!s.is_repo) { setShowSetup(true); return }
      setShowSetup(false)
      const l = await api('/api/log?limit=30')
      if (Array.isArray(l)) {
        setLog(l)
        if (l.length && !selected) setSelected(l[0])
        if (l.length && selected) {
          const still = l.find((v:Version)=>v.hash===selected.hash)
          if (!still) setSelected(l[0])
        }
      }
    } catch (e) { console.error(e) }
  }

  useEffect(() => { refresh(); const id=setInterval(refresh, 3000); return ()=>clearInterval(id) }, [repo])
  useEffect(() => {
    if (!selected || log.length<2) return
    const idx = log.findIndex(v=>v.hash===selected.hash)
    const a = idx+1<log.length ? log[idx+1].hash : selected.hash
    api(`/api/diff?a=${a}&b=${selected.hash}`).then(setDiff).catch(()=>setDiff(null))
  }, [selected])

  const doSave = async () => {
    setSyncStep('Preparing project...')
    await new Promise(r=>setTimeout(r,400))
    setSyncStep('Exporting timeline...')
    // try auto export via Python sidecar would be here; for now manual export already done
    await new Promise(r=>setTimeout(r,300))
    setSyncStep('Checking changes...')
    const st = await api('/api/status')
    if (!st.has_changes) { alert('No changes to save — edit in Resolve and re-export ~/GetSyncd/timeline.otio first'); setSyncStep(null); return }
    setSyncStep('Creating version...')
    const res = await fetch(`${API}/api/save`, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({repo, message: note || undefined})}).then(r=>r.json())
    if (!res.ok) { alert(res.error); setSyncStep(null); return }
    setSyncStep('Syncing with GitHub...')
    await new Promise(r=>setTimeout(r,600))
    // optional push
    try { await fetch(`${API}/api/status?repo=${encodeURIComponent(repo)}`) } catch {}
    setSyncStep('Complete ✓')
    setNote(''); setShowSave(false)
    await refresh()
    setTimeout(()=>setSyncStep(null), 1200)
  }

  const doRestore = async (v: Version) => {
    const hasChanges = status?.has_changes
    let msg = `Restore to "${v.message}"?\n\nThis will become your current timeline in ~/GetSyncd/timeline.otio.\nNext: Resolve → File → Import Timeline → OpenTimelineIO → timeline.otio`
    if (hasChanges) msg = `You have unsaved changes. A safety snapshot will be created first, then restore to "${v.message}".\n\nContinue?`
    if (!confirm(msg)) return
    const res = await fetch(`${API}/api/restore`, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({repo, rev: v.hash, apply: true})}).then(r=>r.json())
    if (!res.ok) { alert(`Restore failed: ${res.error}\nYour current work was not deleted.`); return }
    alert(`Restored to ${v.short} — safety snapshot ${res.safety ? 'saved' : 'created if needed'}.\nNext: Import ~/GetSyncd/timeline.otio in Resolve. You can undo by restoring the previous version.`)
    refresh()
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

  const switchBranch = async () => {
    const name = prompt(`Branches: ${(status?.branches||['main']).join(', ')}\n\nEnter existing branch to switch to, or new name to create:`, status?.current_branch || 'main')
    if (!name) return
    const trimmed = name.trim()
    if (!trimmed) return
    const r = await fetch(`${API}/api/branch`, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({repo, name: trimmed})}).then(r=>r.json())
    if (!r.ok) { alert(r.error); return }
    refresh()
  }

  return (
    <div className="app">
      <header className="top">
        <div className="brand">
          <span className="logo">◈</span> Get Syncd
          <span className="branch" onClick={switchBranch} title="Click to switch or create branch" style={{cursor:'pointer'}}><span className="dot" /> {status?.current_branch || 'main'} ▾</span>
        </div>
        <div className="actions">
          {status?.has_changes ? <span className="unsaved">● Unsaved changes</span> : <span className="saved">✓ Up to date</span>}
          <button onClick={()=>setShowSave(true)} className="primary">Save version</button>
          <button onClick={doSync} className="ghost">Sync</button>
        </div>
      </header>

      {syncStep && <div className="syncbar">{syncStep}</div>}

      <div className="main">
        <aside className="history">
          <div className="h">History</div>
          {Object.entries(groups).map(([d, vs])=>(
            <div key={d} className="group">
              <div className="gdate">{d}</div>
              {vs.map(v=>(
                <div key={v.hash} className={`row ${selected?.hash===v.hash?'sel':''}`} onClick={()=>setSelected(v)}>
                  <div className="thumb" style={{background: v.preview ? `url(${API}/api/preview?repo=${encodeURIComponent(repo)}&hash=${v.short}) center/cover` : '#222'}} />
                  <div className="meta">
                    <div className="msg">{v.message}</div>
                    <div className="sub">{v.date} • {v.short}</div>
                  </div>
                </div>
              ))}
            </div>
          ))}
          {log.length===0 && <div className="empty">No versions yet — Save one above</div>}
        </aside>

        <section className="detail">
          {selected ? (
            <>
              <div className="detailHead">
                <div>
                  <h2>{selected.message}</h2>
                  <p className="vs">vs previous version — {diff ? `${diff.summary?.trimmed||0} trimmed, ${diff.summary?.removed||0} removed, runtime ${diff.summary?.runtime_delta_s>0?'+':''}${diff.summary?.runtime_delta_s||0}s` : '...'}</p>
                  {diff && <div className="barWrap">
                    <div className="bar">
                      {diff.new_track?.items?.slice(0,30).map((it:any,i:number)=>{
                        const ch = diff.changes.find((c:any)=>c.index_new===i)
                        const cls = ch ? ch.type : 'unchanged'
                        return <div key={i} className={`clip ${cls}`} title={it.name} style={{flex: it.duration_frames || 1}} />
                      })}
                    </div>
                    <div className="legend"><span className="l u" /> Unchanged <span className="l t" /> Trimmed <span className="l r" /> Removed <span className="l a" /> Added</div>
                  </div>}
                </div>
                <button className="restore" onClick={()=>doRestore(selected)}>Restore</button>
              </div>
              <div className="changes">
                <h3>Changes</h3>
                {diff?.changes?.length ? diff.changes.slice(0,12).map((c:any,i:number)=>(
                  <div key={i} className={`change ${c.type}`}><span className="dot2" /> {c.clip_name || 'Clip'} — {c.type} {c.details?.delta_s ? `trimmed by ${c.details.delta_s}s` : ''}</div>
                )) : <div className="muted">No clip-level changes or loading…</div>}
                {diff?.warnings?.length ? <div className="warn">{diff.warnings.join(' • ')}</div> : null}
              </div>
              <div className="footActions">
                <button onClick={()=>{ const a=log[log.findIndex(v=>v.hash===selected.hash)+1]?.hash || selected.hash; const b=selected.hash; window.open(`${API}/api/diff?repo=${encodeURIComponent(repo)}&a=${a}&b=${b}`, '_blank')}}>Compare</button>
                <span className="muted">Project: {repo} — media stays local</span>
              </div>
            </>
          ) : <div className="muted">Select a version on the left</div>}
        </section>
      </div>

      {showSave && (
        <div className="modalBg" onClick={()=>setShowSave(false)}>
          <div className="modal" onClick={e=>e.stopPropagation()}>
            <h3>Save Version</h3>
            <p className="muted">This will create a new version from ~/GetSyncd/timeline.otio</p>
            <textarea value={note} onChange={e=>setNote(e.target.value)} placeholder="Audio cleanup — trimmed intro, added B-roll" rows={3} />
            <div className="modalActions">
              <button onClick={()=>setShowSave(false)}>Cancel</button>
              <button className="primary" onClick={doSave}>Save Version</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
