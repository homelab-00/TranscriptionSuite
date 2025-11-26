// Prevents additional console window on Windows in release, DO NOT REMOVE!!
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::process::{Command, Child};
use std::sync::Mutex;

struct BackendProcess(Mutex<Option<Child>>);

fn main() {
    // Start the backend server
    let backend = start_backend();
    
    tauri::Builder::default()
        .manage(BackendProcess(Mutex::new(backend)))
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_http::init())
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                // Stop backend when window closes
                if let Some(state) = window.try_state::<BackendProcess>() {
                    if let Ok(mut guard) = state.0.lock() {
                        if let Some(mut child) = guard.take() {
                            let _ = child.kill();
                        }
                    }
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

fn start_backend() -> Option<Child> {
    // Get the path to the backend directory
    let exe_dir = std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(|p| p.to_path_buf()));
    
    // Try different locations for the backend
    let backend_paths = [
        // Development: relative to project
        std::path::PathBuf::from("../backend"),
        // Production: bundled with app
        exe_dir.clone().map(|p| p.join("../Resources/backend")).unwrap_or_default(),
        exe_dir.map(|p| p.join("backend")).unwrap_or_default(),
    ];
    
    for backend_path in &backend_paths {
        let main_py = backend_path.join("main.py");
        if main_py.exists() {
            // Try to start with uv run first, fall back to python
            if let Ok(child) = Command::new("uv")
                .args(["run", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8000"])
                .current_dir(backend_path)
                .spawn()
            {
                println!("Backend started with uv at {:?}", backend_path);
                return Some(child);
            }
            
            // Fallback to direct python
            if let Ok(child) = Command::new("python")
                .args(["-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8000"])
                .current_dir(backend_path)
                .spawn()
            {
                println!("Backend started with python at {:?}", backend_path);
                return Some(child);
            }
        }
    }
    
    eprintln!("Warning: Could not start backend server");
    None
}
