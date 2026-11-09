import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import {build} from 'esbuild';
import React,{act} from 'react';
import {JSDOM} from 'jsdom';
const bootstrap=new JSDOM('<div></div>',{url:'http://localhost'});globalThis.window=bootstrap.window;globalThis.document=bootstrap.window.document;globalThis.localStorage=bootstrap.window.localStorage;globalThis.navigator=bootstrap.window.navigator;
const {createRoot}=await import('react-dom/client');
const source=(await fs.readFile('src/main.tsx','utf8')).replace(/createRoot\(document\.getElementById\('root'\)!\)\.render\(<React\.StrictMode><App\/><\/React\.StrictMode>\);/,'export {EpisodeDetails};');
await build({stdin:{contents:source,resolveDir:path.resolve('src'),loader:'tsx'},bundle:true,platform:'node',format:'esm',outfile:'work/episode-focus-test.mjs',external:['react','react-dom/client','lucide-react'],plugins:[{name:'mocks',setup(b){b.onResolve({filter:/stores\/api$/},()=>({path:'api',namespace:'mock'}));b.onResolve({filter:/^@tauri-apps\//},()=>({path:'tauri',namespace:'mock'}));b.onResolve({filter:/\.css$/},()=>({path:'css',namespace:'mock'}));b.onLoad({filter:/.*/,namespace:'mock'},a=>({contents:a.path==='api'?`export const api=(...args)=>globalThis.focusApi(...args);export const media=(e,p)=>'/file/'+p;export const upload=async()=>{};export const connect=async()=>{};`:a.path==='tauri'?'export const invoke=async()=>{};export const open=async()=>{};':'',loader:'js'}));}}]});
const {EpisodeDetails}=await import(path.resolve('work/episode-focus-test.mjs'));
const names=['audio_reference','music_brief','music_approval','visual_reference','unity_blueprint','metadata','final_assembly'];
const tasks=names.map(name=>({name,status:'Completed',error:'',started:null,finished:null,execution_kind:'agent',agent_priorities:['codex','antigravity','kimi'],data:{artifacts:[name+'.json']}}));
tasks.find(t=>t.name==='music_brief').data.result={brief:'Music details',prompts:['p1']};
const detail={id:'episode-a',config:{name:'Demo',style:'Coldcore',duration_minutes:60,resolution:'1080p',fps:24,channel_url:'https://youtube.com/@ambient'},tasks,workflow:Object.fromEntries(names.map(n=>[n,[]])),logs:[{id:1,task:'audio_reference',message:'audio event',created:1},{id:2,task:'metadata',message:'metadata event',created:2}],artifacts:names.map(name=>({name:name+'.json',size:1})),references:[],music:[],revisions:[],versions:[],final_current:true};
const visible=(node)=>!!node&&!node.closest('[hidden]');
test('selecting nodes displays only their panels, files and logs; final loads complete history',async()=>{
 const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost'});globalThis.window=dom.window;globalThis.document=dom.window.document;globalThis.localStorage=dom.window.localStorage;globalThis.requestAnimationFrame=(fn)=>fn();dom.window.HTMLElement.prototype.scrollIntoView=()=>{};globalThis.IS_REACT_ACT_ENVIRONMENT=true;
 const calls=[];globalThis.focusApi=async(url)=>{calls.push(url);if(url==='/agents/quotas')return {providers:{}};if(url.endsWith('/history'))return {logs:[...detail.logs,{id:3,task:'metadata',message:'older metadata event',created:0}]};return detail};
 const root=createRoot(document.querySelector('#root'));
 try{
  await act(async()=>{root.render(React.createElement(EpisodeDetails,{id:'episode-a',busy:false,action:async fn=>fn()}));await new Promise(r=>setTimeout(r,0))});
  assert.match(document.querySelector('.logs').textContent,/audio event/);assert.doesNotMatch(document.querySelector('.logs').textContent,/metadata event/);
  assert(!visible(document.querySelector('.channel-metadata')));assert(!document.body.textContent.includes('Music studio'));
  await act(async()=>{document.querySelector('[aria-label="Metadata · Completed"]').click();await new Promise(r=>setTimeout(r,0))});
  assert(visible(document.querySelector('.channel-metadata')));assert.match(document.querySelector('.logs').textContent,/metadata event/);assert.doesNotMatch(document.querySelector('.logs').textContent,/audio event/);
  const artifacts=Array.from(document.querySelectorAll('.artifact')).filter(visible).map(x=>x.textContent);assert(artifacts.some(x=>x.includes('metadata.json')));assert(!artifacts.some(x=>x.includes('audio_reference.json')));
  await act(async()=>{document.querySelector('[aria-label="Final Assembly · Completed"]').click();await new Promise(r=>setTimeout(r,0))});
  assert(calls.includes('/episodes/episode-a/history'));assert.match(document.body.textContent,/Workflow history/);assert.match(document.body.textContent,/older metadata event/);
 }finally{await act(()=>root.unmount());dom.window.close();delete globalThis.focusApi}
});
