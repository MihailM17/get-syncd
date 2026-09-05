#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
  tauri::Builder::default()
    .plugin(tauri_plugin_shell::init())
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
      // NOTE: the spawned Child is intentionally forgotten — dropping it would
      // kill the sidecar; it is meant to live as long as the app.
      std::thread::spawn({
        let handle = app.handle().clone();
        move || {
          use tauri_plugin_shell::ShellExt;
          // give webview a moment
          std::thread::sleep(std::time::Duration::from_millis(500));
          if let Ok(cmd) = handle.shell().sidecar("get-syncd-api") {
            if let Ok((_rx, child)) = cmd.args(["--port", "5174"]).spawn() {
              std::mem::forget(child);
              return;
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
            let res = std::process::Command::new(py)
              .args(["-m", "get_syncd.api_server", "--port", "5174"])
              .spawn();
            if res.is_ok() {
              return;
            }
          }
        }
      });
      Ok(())
    })
    .run(tauri::generate_context!())
    .expect("error while running tauri application");
}
