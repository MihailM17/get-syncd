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
      // 1) bundled sidecar via `externalBin` (per-OS binary built in CI),
      // 2) dev fallback: `python -m get_syncd.api_server`.
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
          // Fallback: try python -m get_syncd.api_server (dev / no bundled sidecar)
          let py_candidates = ["python3", "python"];
          for py in py_candidates {
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
