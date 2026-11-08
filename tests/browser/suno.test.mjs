import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {JSDOM} from 'jsdom';
const source=fs.readFileSync('browser-extension/suno-prep/prep.js','utf8');
function fixture() {
 const dom=new JSDOM(`<form><label for="style">Styles</label><textarea id="style"></textarea><input placeholder="Song Title (Optional)"><div contenteditable="true" aria-label="Lyrics editor"></div><section>
 <input aria-label="Exclude styles">
 <div><span>Vocal Gender</span><button type="button" aria-pressed="false">Male</button><button type="button" aria-pressed="false">Female</button></div>
 <div><span>Max Mode</span><button type="button" aria-pressed="false">Off</button><button type="button" aria-pressed="true">On</button></div>
 <div><span>Personalize</span><button type="button" aria-pressed="true">Off</button><button type="button" aria-pressed="false">On</button></div>
 <input type="range" aria-label="Weirdness" min="0" max="100" value="50">
 <input type="range" aria-label="Style Influence" min="0" max="100" value="50">
 <input type="range" aria-label="Variety" min="0" max="4" value="1">
 <input type="range" aria-label="Duration" min="30" max="600" value="180">
 </section><button type="submit" id="create">Create song</button><button id="download">Download</button></form>`);
 for(const button of dom.window.document.querySelectorAll('button[type="button"]')) button.addEventListener('click',async()=>{
   for(const sibling of button.parentElement.querySelectorAll('button')) sibling.setAttribute('aria-pressed',String(sibling===button && button.getAttribute('aria-pressed')!=='true'));
 });
 const context=vm.createContext({LIMINAL_SUNO_TEST:true,TextDecoder,Uint8Array,atob});
 const api=vm.runInContext(source+';LiminalSunoPrep',context);
 const draft={version:2,id:'a'.repeat(32),account_email:'user@example.com',title:'Ночной поезд <script>no()</script>',styles:'Instrumental ambient pads',instrumental:true,mode:'prepare_only',more_options:{exclude_styles:'vocals, drums',weirdness:25,style_influence:80,variety:'off',duration_seconds:180,max_mode:false,personalize:'off',vocal_gender:'none',rationale:'Low variation and strong style adherence fit a steady beatless ambient brief.'},created:Math.floor(Date.now()/1000)};
 return {doc:dom.window.document,api,draft};
}
test('fills the instrumental form without submitting, clicking or downloading',async()=>{
 const {doc,api,draft}=fixture();let clicks=0,submits=0;
 doc.querySelector('#create').addEventListener('click',()=>clicks++);doc.querySelector('#download').addEventListener('click',()=>clicks++);doc.addEventListener('submit',e=>{e.preventDefault();submits++});
 const result=await api.prepare(doc,draft,'user@example.com');
 assert.equal(result.state,'Prepared');assert.equal(doc.querySelector('textarea').value,draft.styles);
 assert.equal(doc.querySelector('input[placeholder]').value,draft.title);
 assert.equal(doc.querySelector('[contenteditable]').textContent,'');
 assert.equal(clicks,0);assert.equal(submits,0);assert.equal(doc.querySelector('script'),null);
});
test('wrong account and an existing draft leave all fields untouched',async()=>{
 const {doc,api,draft}=fixture();
 await assert.rejects(()=>api.prepare(doc,draft,'someone@example.com'),/account/);
 assert.equal(doc.querySelector('textarea').value,'');
 doc.querySelector('textarea').value='Existing work';
 await assert.rejects(()=>api.prepare(doc,draft,'user@example.com'),/another draft/);
 assert.equal(doc.querySelector('textarea').value,'Existing work');assert.equal(doc.querySelector('input[placeholder]').value,'');
});
test('nonempty lyrics and ambiguous form fields fail before writing',async()=>{
 const {doc,api,draft}=fixture();doc.querySelector('[contenteditable]').textContent='My lyrics';
 await assert.rejects(()=>api.prepare(doc,draft,'user@example.com'),/Lyrics/);
 assert.equal(doc.querySelector('textarea').value,'');
 doc.querySelector('[contenteditable]').textContent='';
 doc.body.insertAdjacentHTML('beforeend','<textarea aria-label="Styles"></textarea>');
 await assert.rejects(()=>api.prepare(doc,draft,'user@example.com'),/form changed/);
 assert.equal(doc.querySelector('input[placeholder]').value,'');
});
test('re-checking the same prepared draft is idempotent',async()=>{
 const {doc,api,draft}=fixture();await api.prepare(doc,draft,'user@example.com');
 assert.equal((await api.prepare(doc,draft,'user@example.com')).state,'Prepared');
});
test('account verification reads Email row, not a connected-account hint',async()=>{
 const {doc,api}=fixture();doc.body.textContent='Account details\nEmail\nuser@example.com\nConnected accounts\nGoogle other@example.com';
 assert.equal(api.accountEmail(doc),'user@example.com');
 doc.body.textContent='Connected accounts\nGoogle user@example.com';assert.equal(api.accountEmail(doc),null);
});
test('expired or generation-enabled payloads are rejected',async()=>{
 const {api,draft}=fixture();assert.throws(()=>api.validate({...draft,mode:'generate'}),/Invalid/);
 assert.throws(()=>api.validate({...draft,created:draft.created-3600}),/expired/);
 assert.throws(()=>api.validate({...draft,instrumental:false}),/Invalid/);
});
test('manifest grants access only to Suno, with no downloads or cookies permission',async()=>{
 const manifest=JSON.parse(fs.readFileSync('browser-extension/suno-prep/manifest.json','utf8'));
 assert.deepEqual(manifest.content_scripts[0].matches,['https://suno.com/*']);
 assert.equal(manifest.permissions,undefined);assert.equal(manifest.host_permissions,undefined);
});

test('missing More Options or missing controls can never return Prepared',async()=>{
 const {doc,api,draft}=fixture();const missing={...draft};delete missing.more_options;
 await assert.rejects(()=>api.prepare(doc,missing,'user@example.com'),/More Options/);
 doc.querySelector('[aria-label="Style Influence"]').remove();
 await assert.rejects(()=>api.prepare(doc,draft,'user@example.com'),/Style Influence/);
});
test('all agent settings are applied and a later change invalidates verification',async()=>{
 const {doc,api,draft}=fixture();await api.prepare(doc,draft,'user@example.com');
 api.verifyOptions(doc,draft.more_options);
 assert.equal(doc.querySelector('[aria-label="Weirdness"]').value,'25');
 assert.equal(doc.querySelector('[aria-label="Style Influence"]').value,'80');
 assert.equal(doc.querySelector('[aria-label="Variety"]').value,'0');
 assert.equal(doc.querySelector('[aria-label="Exclude styles"]').value,'vocals, drums');
 doc.querySelector('[aria-label="Weirdness"]').value='50';
 assert.throws(()=>api.verifyOptions(doc,draft.more_options),/verification failed/);
});

test('Suno HXC selected pills are distinguishable even with two translucent backgrounds',async()=>{
 const {doc,api,draft}=fixture();
 for(const button of doc.querySelectorAll('button[type="button"]')) {
   const active=button.getAttribute('aria-pressed')==='true';
   button.removeAttribute('aria-pressed');button.setAttribute('data-state','closed');
   button.className=active?'hxc-btn-variant-standard-legacy':'hxc-btn-variant-tertiary-legacy';
   button.style.backgroundColor=active?'rgba(255,255,255,.1)':'rgba(40,40,40,.1)';
   button.addEventListener('click',()=>{
     for(const b of button.parentElement.querySelectorAll('button')) b.className=b===button?'hxc-btn-variant-standard-legacy':'hxc-btn-variant-tertiary-legacy';
   });
 }
 await api.prepare(doc,draft,'user@example.com');api.verifyOptions(doc,draft.more_options);
});

test('ignores a hidden native input mirroring a visible named slider',async()=>{
 const {doc,api,draft}=fixture();
 const original=doc.querySelector('[aria-label="Variety"]');original.setAttribute('role','slider');
 const hidden=original.cloneNode();hidden.removeAttribute('role');hidden.value='1';hidden.setAttribute('aria-hidden','true');doc.body.append(hidden);
 await api.prepare(doc,draft,'user@example.com');assert.equal(original.value,'0');assert.equal(hidden.value,'1');
});

test('hidden duplicates of text fields are not mistaken for visible form controls',async()=>{
 const {doc,api,draft}=fixture();const duplicate=doc.querySelector('textarea').cloneNode();duplicate.hidden=true;doc.body.append(duplicate);
 await api.prepare(doc,draft,'user@example.com');assert.equal(duplicate.value,'');
});

test('opens the actual collapsed More Options role-button beside a role-button Reset All',async()=>{
 const {doc,api,draft}=fixture();const section=doc.querySelector('section');section.style.display='none';
 const wrap=doc.createElement('div');section.replaceWith(wrap);
 wrap.innerHTML='<div><div role="button">More Options<span>Variety</span></div><div role="button">Reset All</div></div>';
 wrap.append(section);wrap.querySelector('[role="button"]').addEventListener('click',()=>section.style.display='block');
 await api.prepare(doc,draft,'user@example.com');assert.equal(section.style.display,'block');api.verifyOptions(doc,draft.more_options);
});
