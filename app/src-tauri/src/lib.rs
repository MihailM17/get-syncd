use std::io::{Read, Write};
use std::sync::Mutex;
use std::time::Duration;
use tauri::Manager;

/// Tracked sidecar child so the app can kill it on exit.
/// (Previously the Child was `mem::forget`-ten — it outlived the app and
/// squatted 5174 forever as an orphan after every update.)
struct SidecarState(Mutex<Option<tauri_plugin_shell::process::CommandChild>>);
/// Dev-fallback `python -m get_syncd.api_server` children (same lifecycle).
struct DevSidecars(Mutex<Vec<std::process::Child>>);

/// Minimal loopback GET /health without new deps.
/// Returns (version, pid, started) on success.
fn fetch_health(port: u16) -> Option<(String, u32, f64)> {
  let addr: std::net::SocketAddr = format!("127.0.0.1:{port}").parse().ok()?;
  let mut stream = std::net::TcpStream::connect_timeout(&addr, Duration::from_millis(400)).ok()?;
  stream.set_read_timeout(Some(Duration::from_millis(800))).ok()?;
  stream.set_write_timeout(Some(Duration::from_millis(400))).ok()?;
  stream.write_all(b"GET /health HTTP/1.0\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n").ok()?;
  let mut buf = String::new();
  stream.read_to_string(&mut buf).ok()?;
  let body = buf.split("\r\n\r\n").last().unwrap_or("");
  // Body may have leading junk if the server speaks HTTP/1.1 chunked — find JSON start.
  let json_start = body.find('{')?;
  let v: serde_json::Value = serde_json::from_str(&body[json_start..]).ok()?;
  if !v.get("ok")?.as_bool()? {
    return None;
  }
  let version = v.get("version")?.as_str()?.to_string();
  let pid = v.get("pid")?.as_u64()? as u32;
  let started = v.get("started")?.as_f64().unwrap_or(0.0);
  Some((version, pid, started))
}

/// Best-effort POST /api/shutdown to a stale local daemon (loopback only).
fn request_shutdown(port: u16) -> bool {
  let addr: std::net::SocketAddr = match format!("127.0.0.1:{port}").parse() {
    Ok(a) => a,
    Err(_) => return false,
  };
  let mut stream = match std::net::TcpStream::connect_timeout(&addr, Duration::from_millis(400)) {
    Ok(s) => s,
    Err(_) => return false,
  };
  let _ = stream.set_read_timeout(Some(Duration::from_millis(1200)));
  let _ = stream.set_write_timeout(Some(Duration::from_millis(400)));
  let req = "POST /api/shutdown HTTP/1.0\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}";
  if stream.write_all(req.as_bytes()).is_err() {
    return false;
  }
  let mut buf = String::new();
  if stream.read_to_string(&mut buf).is_err() {
    return false;
  }
  // Match the HTTP status line ("HTTP/1.0 200 ..."), not a stray "200" in a body.
  let status_ok = buf.lines().next().is_some_and(|l| l.contains(" 200 "));
  status_ok && buf.contains("\"ok\"")
}

fn kill_managed(handle: &tauri::AppHandle) {
  if let Some(state) = handle.try_state::<SidecarState>() {
    if let Some(child) = state.0.lock().map(|mut g| g.take()).unwrap_or(None) {
      let pid = child.pid();
      if let Err(e) = child.kill() {
        log::warn!("sidecar kill (pid {pid}) failed: {e}");
      } else {
        log::info!("sidecar (pid {pid}) killed on app exit");
      }
    }
  }
  if let Some(state) = handle.try_state::<DevSidecars>() {
    let mut guard = match state.0.lock() {
      Ok(g) => g,
      Err(_) => return,
    };
    for mut child in guard.drain(..) {
      let _ = child.kill();
      let _ = child.wait();
    }
  }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
  tauri::Builder::default()
    .plugin(tauri_plugin_shell::init())
    .manage(SidecarState(Mutex::new(None)))
    .manage(DevSidecars(Mutex::new(Vec::new())))
    .setup(|app| {
      if cfg!(debug_assertions) {
        app.handle().plugin(
          tauri_plugin_log::Builder::default()
            .level(log::LevelFilter::Info)
            .build(),
        )?;
      }
      // Auto-start Python sidecar (get-syncd API) so a release install just works:
      // 1) bundled sidecar via `externalBin` (deterministic, versioned with the app),
      // 2) dev fallback: `python -m get_syncd.api_server`, but only when that
      //    interpreter actually has get_syncd installed (a bare `spawn`
      //    succeeding means nothing — the child may exit immediately with
      //    ModuleNotFoundError, and we must NOT return early in that case).
      //
      // Lifecycle (orphan fix):
      // - Before spawning, ask stale different-version daemons on 5174..5183
      //   to shut down cleanly (POST /api/shutdown) so updates stop stacking
      //   orphans. Same-version daemons are left alone.
      // - Then ALWAYS spawn: the Python singleton is the single election
      //   point (it compares version AND frozen build id). A redundant new
      //   process that finds a live same daemon just prints "reusing it" and
      //   exits, so no orphans can stack up from races or double-launch.
      // - The spawned Child is TRACKED in state and killed on app exit —
      //   never `mem::forget`-ten. Note the frozen binary is a bootloader
      //   parent + Python child: killing the bootloader orphans the server,
      //   so the server also runs a parent-watchdog and shuts itself down
      //   (runtime file included) when its parent goes away.
      std::thread::spawn({
        let handle = app.handle().clone();
        move || {
          use tauri_plugin_shell::ShellExt;
          // give webview a moment
          std::thread::sleep(Duration::from_millis(500));
          let app_version = env!("CARGO_PKG_VERSION");

          let mut saw_stale = false;
          for port in 5174..5184u16 {
            if let Some((ver, pid, _)) = fetch_health(port) {
              if ver != app_version {
                saw_stale = true;
                log::info!("asking stale sidecar v{ver} (pid {pid}) on :{port} to shut down");
                if request_shutdown(port) {
                  log::info!("stale sidecar on :{port} accepted shutdown");
                }
              }
            }
          }
          if saw_stale {
            // Give stale daemons a moment to exit and free 5174 before we bind.
            std::thread::sleep(Duration::from_millis(900));
          }

          if let Ok(cmd) = handle.shell().sidecar("get-syncd-api") {
            match cmd.args(["--port", "5174"]).spawn() {
              Ok((_rx, child)) => {
                log::info!("spawned sidecar (pid {})", child.pid());
                if let Some(state) = handle.try_state::<SidecarState>() {
                  *state.0.lock().unwrap() = Some(child);
                }
                return;
              }
              Err(e) => log::warn!("sidecar spawn failed: {e}"),
            }
          }
          // Fallback for dev machines: only use interpreters that can import us.
          let py_candidates = ["python3", "python"];
          for py in py_candidates {
            let has_pkg = std::process::Command::new(py)
              .args(["-c", "import get_syncd.api_server"])
              .output()
              .map(|o| o.status.success())
              .unwrap_or(false);
            if !has_pkg {
              continue;
            }
            match std::process::Command::new(py)
              .args(["-m", "get_syncd.api_server", "--port", "5174"])
              .spawn()
            {
              Ok(child) => {
                log::info!("spawned dev sidecar via {py} (pid {})", child.id());
                if let Some(state) = handle.try_state::<DevSidecars>() {
                  state.0.lock().unwrap().push(child);
                }
                return;
              }
              Err(e) => log::warn!("dev sidecar via {py} failed: {e}"),
            }
          }
        }
      });
      Ok(())
    })
    .build(tauri::generate_context!())
    .expect("error while building tauri application")
    .run(|handle, event| {
      if matches!(
        event,
        tauri::RunEvent::ExitRequested { .. } | tauri::RunEvent::Exit
      ) {
        kill_managed(handle);
      }
    });
}
