#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
  tauri::Builder::default()
    .setup(|app| {
      if cfg!(debug_assertions) {
        app.handle().plugin(
          tauri_plugin_log::Builder::default()
            .level(log::LevelFilter::Info)
            .build(),
        )?;
      }
      // Auto-start Python sidecar (get-syncd API) if available — so double-click .app just works
      // Tries: 1) bundled sidecar binary (app/src-tauri/binaries/get-syncd-api-*), 2) python -m get_syncd.api_server
      std::thread::spawn(|| {
        // give webview a moment
        std::thread::sleep(std::time::Duration::from_millis(500));
        // Try bundled sidecar first
        let bins = [
          "binaries/get-syncd-api-aarch64-apple-darwin",
          "binaries/get-syncd-api",
        ];
        for b in bins {
          let p = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join(b);
          if p.exists() {
            let _ = std::process::Command::new(p).arg("--port").arg("5174").spawn();
            return;
          }
        }
        // Fallback: try python -m get_syncd.api_server (dev)
        let py_candidates = ["python3", "python"];
        for py in py_candidates {
          let res = std::process::Command::new(py)
            .args(["-m", "get_syncd.api_server", "--port", "5174"])
            .spawn();
          if res.is_ok() {
            return;
          }
        }
      });
      Ok(())
    })
    .run(tauri::generate_context!())
    .expect("error while running tauri application");
}
