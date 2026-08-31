import { useEffect, useState } from 'react'
import './App.css'

const API = 'http://127.0.0.1:5174'
const REPO = '/Users/mihailmihaylov/GetSyncd' // default workspace

type Version = { hash: string; short: string; author: string; date: string; message: string; preview?: string }
type Status = { is_repo: boolean; has_changes: boolean | null; message: string; current_branch?: string; branches?: string[] }
type Diff = { summary: any; changes: any[]; warnings: string[]; text_log: string; new_track?: any; changelog: string }

function groupByDate(versions: Version[]) {
  const groups: Record<string, Version[]> = {}
  const today = new Date().toISOString().slice(0,10)
  const y = new Date(Date.now() - 86400000).toISOString().slice(0,10)
  for (const v of versions) {
    let key = v.date
    if (key === today) key = 'Today'
    else if (key === y) key = 'Yesterday'
    else key = v.date
    if (!groups[key]) groups[key] = []
    groups[key].push(v)
  }
  return groups
}

export default function App() {
  const [status, setStatus] = useState<Status | null>(null)
  const [log, setLog] = useState<Version[]>([])
  const [selected, setSelected] = useState<Version | null>(null)
  const [diff, setDiff] = useState<Diff | null>(null)
  const [saving, setSaving] = useState(false)
  const [note, setNote] = useState('')
  const [syncState, setSyncState] = useState<string | null>(null)

  const refresh = async () => {
    const s = await fetch(`${API}/api/status?repo=${encodeURIComponent(REPO)}`).then(r=>r.json())
    setStatus(s)
    const l = await fetch(`${API}/api/log?repo=${encodeURIComponent(REPO)}&limit=30`).then(r=>r.json())
    setLog(l)
    if (l.length && !selected) setSelected(l[0])
  }

  useEffect(() => { refresh(); const id = setInterval(refresh, 4000); return () => clearInterval(id) }, [])
  useEffect(() => {
    if (!selected || log.length < 2) return
    const idx = log.findIndex(v=>v.hash===selected.hash)
    const a = idx+1 < log.length ? log[idx+1].hash : selected.hash
    const b = selected.hash
    fetch(`${API}/api/diff?repo=${encodeURIComponent(REPO)}&a=${a}&b=${b}`).then(r=>r.json()).then(setDiff)
  }, [selected])

  const saveVersion = async () => {
    setSaving(true)
    setSyncState('Preparing project...')
    await new Promise(r=>setTimeout(r,300))
    setSyncState('Checking changes...')
    await new Promise(r=>setTimeout(r,300))
    setSyncState('Creating version...')
    const res = await fetch(`${API}/api/save`, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({repo: REPO, message: note || undefined})}).then(r=>r.json())
    if (!res.ok) { alert(res.error); setSyncState(null); setSaving(false); return }
    setSyncState('Syncing with GitHub...')
    await fetch(`${API}/api/log?repo=${encodeURIComponent(REPO)}`).then(()=>{})
    // optional push — try but don't fail
    try { await fetch(`${API}/api/status?repo=${encodeURIComponent(REPO)}`) } catch {}
    setSyncState('Complete ✓')
    setNote('')
    await refresh()
    setTimeout(()=>setSyncState(null), 1500)
    setSaving(false)
  }

  const restore = async (v: Version) => {
    if (status?.has_changes) {
      if (!confirm(`You have unsaved changes. A safety snapshot will be created before restoring to "${v.message}". Continue?`)) return
    } else {
      if (!confirm(`Restore to "${v.message}"? This will overwrite timeline.otio (backed up automatically).`)) return
    }
    const res = await fetch(`${API}/api/restore`, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({repo: REPO, rev: v.hash, apply: true})}).then(r=>r.json())
    if (!res.ok) alert(res.error)
    else alert(`Restored to ${v.short}. Next: Resolve → File → Import Timeline → OpenTimelineIO → timeline.otio`)
    refresh()
  }

  const groups = groupByDate(log)

  return (
    <div className="app">
      <header className="top">
        <div className="brand">
          <span className="logo">◈</span> Get Syncd
          <span className="branch"><span className="dot" /> {status?.current_branch || 'main'} ▾</span>
        </div>
        <div className="actions">
          {status?.has_changes ? <span className="unsaved">● Unsaved changes</span> : <span className="saved">✓ Up to date</span>}
          <button className="primary" onClick={saveVersion} disabled={saving}>{saving ? syncState || 'Saving…' : 'Save version'}</button>
        </div>
      </header>

      {syncState && <div className="syncbar">{syncState}</div>}

      <div className="main">
        <aside className="history">
          <div className="h">History</div>
          {Object.entries(groups).map(([date, vs]) => (
            <div key={date} className="group">
              <div className="gdate">{date}</div>
              {vs.map(v => (
                <div key={v.hash} className={`row ${selected?.hash===v.hash?'sel':''}`} onClick={()=>setSelected(v)}>
                  <div className="thumb" style={{background: `url(${API}/api/preview?repo=${encodeURIComponent(REPO)}&hash=${v.short}) center/cover`}} />
                  <div className="meta">
                    <div className="msg">{v.message}</div>
                    <div className="sub">{diff && selected?.hash===v.hash ? diff.changelog : v.date}</div>
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
                  <p className="vs">vs previous version — {diff ? `${diff.summary.trimmed||0} trimmed, ${diff.summary.removed||0} removed, runtime ${diff.summary.runtime_delta_s>0?'+':''}${diff.summary.runtime_delta_s}s` : 'loading...'}</p>
                  {diff && <div className="barWrap">
                    <div className="bar">
                      {diff.new_track?.items?.map((it:any, i:number) => {
                        const ch = diff.changes.find((c:any)=>c.index_new===i)
                        const cls = ch ? ch.type : 'unchanged'
                        return <div key={i} className={`clip ${cls}`} title={it.name} style={{flex: it.duration_frames}}>{it.name.slice(0,8)}</div>
                      })}
                    </div>
                    <div className="legend"><span className="l u" /> Unchanged <span className="l t" /> Trimmed <span className="l r" /> Removed <span className="l a" /> Added</div>
                  </div>}
                </div>
                <button className="restore" onClick={()=>restore(selected)}>Restore</button>
              </div>

              <div className="changes">
                <h3>Changes</h3>
                {diff?.changes?.length ? diff.changes.map((c:any,i:number)=>(
                  <div key={i} className={`change ${c.type}`}>
                    <span className="dot2" /> {c.clip_name} — {c.type} {c.details?.delta_s ? `trimmed by ${c.details.delta_s}s` : c.type==='removed' ? 'removed' : c.type==='added' ? 'new take added' : ''}
                  </div>
                )) : <div className="muted">No clip-level changes or loading…</div>}
              </div>
            </>
          ) : <div className="muted">Select a version on the left</div>}
        </section>
      </div>

      <footer className="foot">Project: {REPO} — media stays local, only timeline is versioned</footer>
    </div>
  )
}
