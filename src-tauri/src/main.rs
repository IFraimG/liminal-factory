#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
use std::{io::{BufRead,BufReader},process::{Child,Command,Stdio},sync::Mutex};
use tauri::Manager;
#[derive(Clone,serde::Serialize)]
struct Bridge { url:String, token:String }
struct Backend { child:Mutex<Child>, bridge:Bridge }
#[tauri::command]
fn bridge(state:tauri::State<Backend>)->Bridge { state.bridge.clone() }
#[tauri::command]
fn open_suno()->Result<(),String> {Command::new("/usr/bin/open").arg("https://suno.com/create").spawn().map(|_|()).map_err(|e|e.to_string())}
#[tauri::command]
fn open_suno_draft(url:String)->Result<(),String> {
 let prefix="https://suno.com/create#liminal-draft=";
 let payload=url.strip_prefix(prefix).ok_or("Invalid Suno preparation URL")?;
 if payload.is_empty() || payload.len()>10000 || !payload.bytes().all(|c|c.is_ascii_alphanumeric() || c==b'-' || c==b'_') {return Err("Invalid Suno preparation payload".into());}
 Command::new("/usr/bin/open").args(["-a","Google Chrome",&url]).spawn().map(|_|()).map_err(|e|e.to_string())
}
fn main(){
 let app=tauri::Builder::default().plugin(tauri_plugin_dialog::init()).setup(|app|{
   let token=uuid::Uuid::new_v4().to_string()+&uuid::Uuid::new_v4().to_string();
   let mut command;
   if cfg!(debug_assertions) {
     let root=std::path::Path::new(env!("CARGO_MANIFEST_DIR")).parent().unwrap();
     command=Command::new(root.join(".venv/bin/python"));command.args(["-m","backend.main"]).current_dir(root);
   } else {
     let exe=app.path().resource_dir()?.join("backend/liminal-backend"); command=Command::new(exe);
   }
   // Augment common macOS tool locations; preserve provider auth environment without storing credentials.
   let search=format!("{}/.local/bin:/opt/homebrew/bin:/usr/local/bin:{}",std::env::var("HOME").unwrap_or_default(),std::env::var("PATH").unwrap_or_default());
   let mut child=command.env("LIMINAL_TOKEN",&token).env("PATH",search).stdout(Stdio::piped()).stderr(Stdio::inherit()).spawn()?;
   let stdout=child.stdout.take().unwrap();
   let (tx,rx)=std::sync::mpsc::channel();
   std::thread::spawn(move || {let mut reader=BufReader::new(stdout);let mut line=String::new();let result=reader.read_line(&mut line).map(|_|line).map_err(|e|e.to_string());let _=tx.send(result);for _ in reader.lines() {}});
   let line=match rx.recv_timeout(std::time::Duration::from_secs(30)) {Ok(Ok(line))=>line,_=>{let _=child.kill();return Err("Backend did not initialize in 30 seconds".into());}};
   let value:serde_json::Value=serde_json::from_str(&line)?;
   let url=value["url"].as_str().ok_or("Backend failed to initialize")?.to_string();

   app.manage(Backend{child:Mutex::new(child),bridge:Bridge{url,token}});Ok(())
 }).invoke_handler(tauri::generate_handler![bridge,open_suno,open_suno_draft]).build(tauri::generate_context!()).expect("Unable to start Liminal Factory backend");
 app.run(|handle,event| {if let tauri::RunEvent::Exit=event {if let Some(state)=handle.try_state::<Backend>() {if let Ok(mut child)=state.child.lock() {unsafe{libc::kill(child.id() as i32,libc::SIGTERM);}let _=child.wait();}}}});
}
