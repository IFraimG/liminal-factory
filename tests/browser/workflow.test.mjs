import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import {build} from 'esbuild';
import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
import {JSDOM} from 'jsdom';
await fs.mkdir('work',{recursive:true});
await build({stdin:{contents:"export {PipelineGraph,graphLayout} from './src/components/PipelineGraph'; export {AgentPriorityEditor} from './src/components/AgentPriorityEditor';",resolveDir:process.cwd(),loader:'tsx'},bundle:true,platform:'node',format:'esm',outfile:'work/workflow-test-components.mjs',external:['react','react-dom/client','lucide-react'],plugins:[{name:'test-api',setup(builder){builder.onResolve({filter:/stores\/api$/},()=>({path:'test-api',namespace:'mock'}));builder.onLoad({filter:/.*/,namespace:'mock'},()=>({contents:'export async function api(...args){return globalThis.workflowApi(...args)}',loader:'js'}));}}]});
const {PipelineGraph,graphLayout,AgentPriorityEditor}=await import(path.resolve('work/workflow-test-components.mjs'));
const workflow={audio_reference:[],music_brief:['audio_reference'],music_approval:['music_brief'],audio_engineer:['music_approval'],visual_reference:[],unity_preview:['visual_reference'],visual_approval:['unity_preview'],recording_setup:['visual_approval'],visual_render:['recording_setup'],channel_reference:[],metadata:['channel_reference','music_brief','visual_reference'],final_assembly:['audio_engineer','visual_render','metadata']};
const defaults={status:'Pending',data:{},agent_priorities:['codex','antigravity','kimi'],execution_kind:'agent',priority_locked:false};
async function mount(component){
 const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost'});
 globalThis.window=dom.window;globalThis.document=dom.window.document;globalThis.IS_REACT_ACT_ENVIRONMENT=true;
 const root=createRoot(document.querySelector('#root'));await act(()=>root.render(component));
 return {root,dom,async close(){await act(()=>root.unmount());dom.window.close();delete globalThis.workflowApi;}};
}
const button=(label)=>Array.from(document.querySelectorAll('button')).find(b=>b.getAttribute('aria-label')===label||b.textContent===label);
test('graph shows every step and real cross-pipeline dependencies',async()=>{
 let selected=null;
 const view=await mount(React.createElement(PipelineGraph,{tasks:Object.keys(workflow).map(name=>({...defaults,name,execution_kind:name.endsWith('_approval')?'approval':'agent'})),workflow,selected:'metadata',onSelect:name=>{selected=name}}));
 try{
  assert.equal(document.querySelectorAll('.graph-node').length,12);
  assert.equal(document.querySelectorAll('.graph-edges>path').length,Object.values(workflow).flat().length);
  assert.equal(document.querySelectorAll('.is-gate').length,2);
  const layout=graphLayout(workflow),get=name=>layout.find(n=>n.name===name);
  assert(get('metadata').y>get('music_brief').y);
  assert(get('final_assembly').y>get('visual_render').y);
  await act(()=>button('Unity Preview · Pending').click());assert.equal(selected,'unity_preview');
 }finally{await view.close()}
});
test('priority editor saves only the selected step, in visible order',async()=>{
 const calls=[];globalThis.workflowApi=async(...args)=>{calls.push(args);return {order:args[2].order}};
 const view=await mount(React.createElement(AgentPriorityEditor,{episode:'episode-a',task:{...defaults,name:'metadata'},busy:false,onSave:async()=>{}}));
 try{
  await act(()=>button('Move Kimi K3.1 Pro High up').click());
  await act(()=>button('Move Kimi K3.1 Pro High up').click());
  assert.deepEqual(Array.from(document.querySelectorAll('.priority-list strong')).map(n=>n.textContent),['Kimi K3.1 Pro High','GPT · Codex','Gemini · Argon']);
  assert.equal(calls.length,0);
  await act(()=>button('Save agent priority').click());
  assert.deepEqual(calls,[['/episodes/episode-a/tasks/metadata/priorities','PUT',{order:['kimi','codex','antigravity']}]]);
 }finally{await view.close()}
});
for(const status of ['Running','Waiting for CLI','Waiting for Permission','Waiting for quota'])test(`priority is locked during ${status}`,async()=>{
 const view=await mount(React.createElement(AgentPriorityEditor,{episode:'e',task:{...defaults,name:'unity_preview',status},busy:false,onSave:async()=>{}}));
 try{assert(Array.from(document.querySelectorAll('button')).every(b=>b.disabled));assert.match(document.body.textContent,/Stop this step/)}finally{await view.close()}
});
test('server race rejection is shown and priorities can be refreshed',async()=>{
 let refreshed=0;globalThis.workflowApi=async()=>{throw Error('Stop the active step before changing its agent priorities')};
 const view=await mount(React.createElement(AgentPriorityEditor,{episode:'e',task:{...defaults,name:'metadata'},busy:false,onSave:async()=>{refreshed++}}));
 try{
  await act(()=>button('Move GPT · Codex down').click());await act(()=>button('Save agent priority').click());
  assert.match(document.querySelector('[role=alert]').textContent,/Stop the active step/);assert.equal(refreshed,1);
 }finally{await view.close()}
});
test('approval node never exposes automatic AI approval priority',async()=>{
 const view=await mount(React.createElement(AgentPriorityEditor,{episode:'e',task:{...defaults,name:'visual_approval',execution_kind:'approval'},busy:false,onSave:async()=>{}}));
 try{assert.equal(document.querySelectorAll('.priority-list').length,0);assert.match(document.body.textContent,/manual approval/)}finally{await view.close()}
});
