import {spawnSync} from 'node:child_process';
import {existsSync} from 'node:fs';
import path from 'node:path';
const env={...process.env};
if(existsSync('work/cargo/bin/cargo')) {env.CARGO_HOME=path.resolve('work/cargo');env.RUSTUP_HOME=path.resolve('work/rustup');env.PATH=path.resolve('work/cargo/bin')+':'+env.PATH;}
if(process.argv[2]==='dev'&&!existsSync('src-tauri/binaries/backend/liminal-backend')) {
 const setup=spawnSync('python3',['scripts/bootstrap.py'],{env,stdio:'inherit'});if(setup.status)process.exit(setup.status);
 const pack=spawnSync('.venv/bin/python',['scripts/build_sidecar.py'],{env,stdio:'inherit'});if(pack.status)process.exit(pack.status);
}
const result=spawnSync(path.resolve('node_modules/.bin/tauri'),process.argv.slice(2),{env,stdio:'inherit'});process.exit(result.status??1);
