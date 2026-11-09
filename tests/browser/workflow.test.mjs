import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import {build} from 'esbuild';
import React,{act} from 'react';

import {JSDOM} from 'jsdom';
const bootstrapDom=new JSDOM('<div></div>');globalThis.window=bootstrapDom.window;globalThis.document=bootstrapDom.window.document;globalThis.navigator=bootstrapDom.window.navigator;
const {createRoot}=await import('react-dom/client');
await fs.mkdir('work',{recursive:true});
await build({stdin:{contents:"export {PipelineGraph,graphLayout} from './src/components/PipelineGraph'; export {AgentPriorityEditor} from './src/components/AgentPriorityEditor'; export {FinalReview} from './src/components/FinalReview'; export {ExtendedRelease} from './src/components/ExtendedRelease';",resolveDir:process.cwd(),loader:'tsx'},bundle:true,platform:'node',format:'esm',outfile:'work/workflow-test-components.mjs',external:['react','react-dom/client','lucide-react'],plugins:[{name:'test-api',setup(builder){builder.onResolve({filter:/stores\/api$/},()=>({path:'test-api',namespace:'mock'}));builder.onLoad({filter:/.*/,namespace:'mock'},()=>({contents:"export async function api(...args){return globalThis.workflowApi(...args)}; export function media(e,p){return '/episodes/'+e+'/file/'+p}",loader:'js'}));}}]});
const {PipelineGraph,graphLayout,AgentPriorityEditor,FinalReview,ExtendedRelease}=await import(path.resolve('work/workflow-test-components.mjs'));
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

const finalDetail={id:'episode-a',final_current:true,artifacts:[{name:'output/final.mp4',modified:123}],versions:[],revisions:[]};
test('final revision defaults to GPT Sol Medium and submits only explicit prompt and scope',async()=>{
 const calls=[];globalThis.workflowApi=async(...args)=>{calls.push(args);return {id:'revision-1'}};
 let refreshed=0;const view=await mount(React.createElement(FinalReview,{detail:finalDetail,onRefresh:async()=>{refreshed++}}));
 try{
  assert.match(document.querySelector('select').selectedOptions[0].textContent,/GPT-6.1 Sol.*Medium/);
  const input=document.querySelector('textarea');
  await act(()=>{Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype,'value').set.call(input,'Make the Unity fog lighter');input.dispatchEvent(new window.Event('input',{bubbles:true}));input.dispatchEvent(new window.Event('change',{bubbles:true}));});
  await act(()=>document.querySelector('form').dispatchEvent(new window.Event('submit',{bubbles:true,cancelable:true})));
  assert.equal(calls.length,1);assert.equal(calls[0][0],'/episodes/episode-a/revisions');
  assert.equal(calls[0][2].prompt,'Make the Unity fog lighter');assert.equal(calls[0][2].provider,'codex');assert.equal(calls[0][2].scope,'auto');assert.equal(refreshed,1);
 }finally{await view.close()}
});
test('superseded final stays available while replacement is pending',async()=>{
 const detail={...finalDetail,final_current:false,versions:[{id:'v1',created:123,status:'superseded',video:'versions/v1/files/output/final.mp4',manifest_path:'versions/v1/manifest.json',integrity_warnings:['older scene hash changed']}]};
 const view=await mount(React.createElement(FinalReview,{detail,onRefresh:async()=>{}}));
 try{
  assert.match(document.querySelector('video').src,/versions\/v1\/files/);
  assert.equal(document.querySelectorAll('video').length,1);assert(document.querySelector('textarea').disabled);
  assert.match(document.querySelector('summary').textContent,/superseded/);assert.match(document.body.textContent,/observed files and their checksums/);
 }finally{await view.close()}
});
test('ongoing revision locks duplicate submission and can be cancelled',async()=>{
 const calls=[];globalThis.workflowApi=async(...args)=>{calls.push(args)};
 const view=await mount(React.createElement(FinalReview,{detail:{...finalDetail,revisions:[{id:'r1',provider:'codex',status:'Waiting for quota',prompt:'Lighter fog',data:{}}]},onRefresh:async()=>{}}));
 try{
  assert(document.querySelector('textarea').disabled);assert(button('Request revision').disabled);
  await act(()=>button('Cancel revision analysis').click());
  assert.deepEqual(calls,[['/episodes/episode-a/revisions/r1/cancel','POST']]);
 }finally{await view.close()}
});

const clarificationRow={id:'r-question',provider:'codex',status:'Needs clarification',prompt:'Make the scene more realistic',error:'May the composition change?',data:{plan:{explanation:'Need your choice first',needs_clarification:true,clarification:'May the composition change?'},messages:[{id:'original',role:'user',content:'Make the scene more realistic',created:100},{id:'question-1',role:'assistant',kind:'question',content:'May the composition change?',created:101}]}};
async function answerText(text){const input=document.querySelector('[aria-label="Your answer to the agent"]');await act(()=>{Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype,'value').set.call(input,text);input.dispatchEvent(new window.Event('input',{bubbles:true}));});}
test('answer continues the same revision and keeps both rounds visible after refresh',async()=>{
 const calls=[];globalThis.workflowApi=async(...args)=>{calls.push(args);return {id:'r-question'}};
 let detail={...finalDetail,revisions:[clarificationRow]},view;
 async function refresh(){detail={...detail,revisions:[{...clarificationRow,data:{...clarificationRow.data,messages:[...clarificationRow.data.messages,{id:'answer-1',role:'user',content:'Да, сохраните музыку',created:102,reply_to:'question-1'},{id:'question-2',role:'assistant',kind:'question',content:'Keep the current camera?',created:103}]}}]};await view.root.render(React.createElement(FinalReview,{detail,onRefresh:refresh}));}
 view=await mount(React.createElement(FinalReview,{detail,onRefresh:refresh}));
 try{
  assert.match(document.querySelector('[role=log]').textContent,/May the composition change/);
  await answerText('Да, сохраните музыку');await act(()=>document.querySelector('.revision-reply').dispatchEvent(new window.Event('submit',{bubbles:true,cancelable:true})));
  assert.deepEqual(calls,[['/episodes/episode-a/revisions/r-question/reply','POST',{question_id:'question-1',answer:'Да, сохраните музыку'}]]);
  const history=document.querySelector('[role=log]').textContent;
  for(const text of ['Make the scene more realistic','May the composition change?','Да, сохраните музыку','Keep the current camera?'])assert(history.includes(text));
  assert.equal(document.querySelector('[aria-label="Your answer to the agent"]').value,'');
 }finally{await view.close()}
});
test('failed reply preserves the draft and displays the rejection',async()=>{
 globalThis.workflowApi=async()=>{throw Error('This question has already been answered; refresh')};
 const view=await mount(React.createElement(FinalReview,{detail:{...finalDetail,revisions:[clarificationRow]},onRefresh:async()=>{}}));
 try{
  await answerText('Нет');await act(()=>document.querySelector('.revision-reply').dispatchEvent(new window.Event('submit',{bubbles:true,cancelable:true})));
  assert.equal(document.querySelector('[aria-label="Your answer to the agent"]').value,'Нет');
  assert.match(document.querySelector('[role=alert]').textContent,/already been answered/);
 }finally{await view.close()}
});
test('conversation stays visible without an answer form while the agent is running',async()=>{
 const view=await mount(React.createElement(FinalReview,{detail:{...finalDetail,revisions:[{...clarificationRow,status:'Planning'}]},onRefresh:async()=>{}}));
 try{assert(document.querySelector('[role=log]'));assert.equal(document.querySelector('.revision-reply'),null);assert(button('Request revision').disabled)}finally{await view.close()}
});

const releaseDetail={...finalDetail,config:{recording_minutes:3},presentation:{enabled:false},tasks:[{name:'visual_render',status:'Completed',data:{}}]};
test('extended release defaults to one hour and keeps the Unity capture separate',async()=>{
 const calls=[];globalThis.workflowApi=async(...args)=>{calls.push(args)};
 const view=await mount(React.createElement(ExtendedRelease,{detail:releaseDetail,onRefresh:async()=>{}}));
 try{
  assert.equal(document.querySelector('[aria-label="Release duration (minutes)"]').value,'60');
  assert.match(document.querySelector('video').src,/visual-recording.mp4/);
  await act(()=>document.querySelector('form').dispatchEvent(new window.Event('submit',{bubbles:true,cancelable:true})));
  assert.deepEqual(calls,[['/episodes/episode-a/presentation','POST',{minutes:60,mode:'video',prompt:''}]]);
 }finally{await view.close()}
});
test('image path requests an edit and shows approval and iteration history',async()=>{
 const calls=[];globalThis.workflowApi=async(...args)=>{calls.push(args)};
 const detail={...releaseDetail,config:{...releaseDetail.config,presentation_mode:'image',presentation_minutes:60},tasks:[...releaseDetail.tasks,{name:'audio_engineer',status:'Running',data:{}},{name:'image_edit',status:'Completed',data:{image:'image-edits/one/edited.png'}},{name:'image_approval',status:'Waiting for Approval',data:{}}],presentation:{enabled:true,image_history:[{image:'image-edits/one/edited.png',prompt:'More realistic lighting',description:'Edited lighting',created:1}]}};
 const view=await mount(React.createElement(ExtendedRelease,{detail,onRefresh:async()=>{}}));
 try{
  assert.equal(document.querySelector('[aria-label="Visual source"]').value,'image');assert(document.querySelector('img'));
  assert.match(document.body.textContent,/Image edit history/);
  assert.equal(button('Approve image and extend video').disabled,false);
  await act(()=>button('Approve image and extend video').click());
  assert.deepEqual(calls,[['/episodes/episode-a/tasks/image_approval/approve','POST']]);
 }finally{await view.close()}
});
