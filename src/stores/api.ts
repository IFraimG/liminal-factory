import {invoke} from '@tauri-apps/api/core';
let connection:{url:string;token:string};
export async function connect(){connection=await invoke('bridge');}
export async function api<T=unknown>(path:string,method='GET',data?:unknown):Promise<T>{
 if(!connection)throw Error('Backend is not connected. Launch with npm run tauri dev.');
 const response=await fetch(connection.url+path,{method,headers:{Authorization:'Bearer '+connection.token,'Content-Type':'application/json'},body:data===undefined?undefined:JSON.stringify(data)});
 if(!response.ok){const body=await response.json();throw Error(typeof body.detail==='string'?body.detail:JSON.stringify(body.detail));}return response.json();
}
export function media(id:string,path:string){return connection.url+`/episodes/${id}/file/`+path.split('/').map(encodeURIComponent).join('/')+'?token='+encodeURIComponent(connection.token);}
export async function upload(id:string,kind:string,file:File){
 if(file.size>70*1024*1024)throw Error('Maximum file size: 70 MB');
 const base64=await new Promise<string>((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(String(r.result).split(',')[1]);r.onerror=reject;r.readAsDataURL(file);});
 return api(`/episodes/${id}/imports/${kind}`,'POST',{name:file.name,base64});
}
