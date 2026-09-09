#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use serde_json::{json, Value};
use std::{collections::HashMap, io::{BufRead, Write}, sync::{Arc, Mutex, atomic::{AtomicU64, Ordering}}};
use tokio::sync::oneshot;
use tauri::Manager;

// Anonymous OS pipes connect to the existing Qt process. No HTTP listener,
// access token, filesystem access, or arbitrary shell API is exposed to JS.
type Pending = Arc<Mutex<HashMap<u64, oneshot::Sender<Value>>>>;
struct Bridge { pending: Pending, next: AtomicU64 }

#[tauri::command]
async fn settings_call(method: String, args: Vec<Value>, bridge: tauri::State<'_, Bridge>) -> Result<Value, String> {
    if method.len() > 80 || args.len() > 8 {
        return Err("Invalid settings request".into());
    }
    let id = bridge.next.fetch_add(1, Ordering::Relaxed);
    let (tx, rx) = oneshot::channel();
    bridge.pending.lock().map_err(|_| "Bridge unavailable")?.insert(id, tx);
    let request = json!({"id": id, "method": method, "args": args});
    let sent = {
        let mut out = std::io::stdout().lock();
        writeln!(out, "{}", request).and_then(|_| out.flush())
    };
    if sent.is_err() {
        bridge.pending.lock().map_err(|_| "Bridge unavailable")?.remove(&id);
        return Err("Clarify is not connected".into());
    }
    let result = tokio::time::timeout(std::time::Duration::from_secs(15), rx).await;
    bridge.pending.lock().map_err(|_| "Bridge unavailable")?.remove(&id);
    let response = result.map_err(|_| "Clarify did not respond")?.map_err(|_| "Clarify disconnected")?;
    if let Some(error) = response.get("error").and_then(Value::as_str) {
        return Err(error.into());
    }
    Ok(response["result"].clone())
}

fn main() {
    let pending: Pending = Arc::new(Mutex::new(HashMap::new()));
    let reader = pending.clone();
    tauri::Builder::default()
        .manage(Bridge { pending, next: AtomicU64::new(1) })
        .setup(move |app| {
          let handle = app.handle().clone();
          std::thread::spawn(move || {
        for line in std::io::stdin().lock().lines() {
            let Ok(line) = line else { break };
            if line.len() > 1_048_576 { continue; }
            let Ok(value) = serde_json::from_str::<Value>(&line) else { continue };
            if let Some(action) = value["window"].as_str() {
                if let Some(window) = handle.get_webview_window("main") {
                    match action {
                        "show" => { let _ = window.unminimize(); let _ = window.show(); let _ = window.set_focus(); },
                        "hide" => { let _ = window.hide(); },
                        _ => {}
                    }
                }
                continue;
            }
            if let Some(id) = value["id"].as_u64() {
                if let Some(tx) = reader.lock().unwrap().remove(&id) { let _ = tx.send(value); }
            }
        }
        reader.lock().unwrap().clear();
        handle.exit(0);
          });
          Ok(())
        })
        .invoke_handler(tauri::generate_handler![settings_call])
        .run(tauri::generate_context!())
        .expect("Could not start Clarify settings");
}
