import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {JSDOM} from 'jsdom';
const source=fs.readFileSync('browser-extension/suno-prep/prep.js','utf8');
function fixture() {
 const dom=new JSDOM(`<form><label for="style">Styles</label><textarea id="style"></textarea><input placeholder="Song Title (Optional)"><div contenteditable="true" aria-label="Lyrics editor"></div><button type="submit">Create song</button><button>Download</button></form>`);
 const context=vm.createContext({LIMINAL_SUNO_TEST:true,TextDecoder,Uint8Array,atob});
 const api=vm.runInContext(source+';LiminalSunoPrep',context);
 const draft={version:1,id:'a'.repeat(32),account_email:'user@example.com',title:'Ночной поезд <script>no()</script>',styles:'Instrumental ambient pads',instrumental:true,mode:'prepare_only',created:Math.floor(Date.now()/1000)};
 return {doc:dom.window.document,api,draft};
}
test('fills the instrumental form without submitting, clicking or downloading',()=>{
 const {doc,api,draft}=fixture();let clicks=0,submits=0;
 doc.addEventListener('click',()=>clicks++);doc.addEventListener('submit',e=>{e.preventDefault();submits++});
 const result=api.prepare(doc,draft,'user@example.com');
 assert.equal(result.state,'Prepared');assert.equal(doc.querySelector('textarea').value,draft.styles);
 assert.equal(doc.querySelector('input').value,draft.title);
 assert.equal(doc.querySelector('[contenteditable]').textContent,'');
 assert.equal(clicks,0);assert.equal(submits,0);assert.equal(doc.querySelector('script'),null);
});
test('wrong account and an existing draft leave all fields untouched',()=>{
 const {doc,api,draft}=fixture();
 assert.throws(()=>api.prepare(doc,draft,'someone@example.com'),/account/);
 assert.equal(doc.querySelector('textarea').value,'');
 doc.querySelector('textarea').value='Existing work';
 assert.throws(()=>api.prepare(doc,draft,'user@example.com'),/another draft/);
 assert.equal(doc.querySelector('textarea').value,'Existing work');assert.equal(doc.querySelector('input').value,'');
});
test('nonempty lyrics and ambiguous form fields fail before writing',()=>{
 const {doc,api,draft}=fixture();doc.querySelector('[contenteditable]').textContent='My lyrics';
 assert.throws(()=>api.prepare(doc,draft,'user@example.com'),/Lyrics/);
 assert.equal(doc.querySelector('textarea').value,'');
 doc.querySelector('[contenteditable]').textContent='';
 doc.body.insertAdjacentHTML('beforeend','<textarea aria-label="Styles"></textarea>');
 assert.throws(()=>api.prepare(doc,draft,'user@example.com'),/form changed/);
 assert.equal(doc.querySelector('input').value,'');
});
test('re-checking the same prepared draft is idempotent',()=>{
 const {doc,api,draft}=fixture();api.prepare(doc,draft,'user@example.com');
 assert.equal(api.prepare(doc,draft,'user@example.com').state,'Prepared');
});
test('account verification reads Email row, not a connected-account hint',()=>{
 const {doc,api}=fixture();doc.body.textContent='Account details\nEmail\nuser@example.com\nConnected accounts\nGoogle other@example.com';
 assert.equal(api.accountEmail(doc),'user@example.com');
 doc.body.textContent='Connected accounts\nGoogle user@example.com';assert.equal(api.accountEmail(doc),null);
});
test('expired or generation-enabled payloads are rejected',()=>{
 const {api,draft}=fixture();assert.throws(()=>api.validate({...draft,mode:'generate'}),/Invalid/);
 assert.throws(()=>api.validate({...draft,created:draft.created-3600}),/expired/);
 assert.throws(()=>api.validate({...draft,instrumental:false}),/Invalid/);
});
test('manifest grants access only to Suno, with no downloads or cookies permission',()=>{
 const manifest=JSON.parse(fs.readFileSync('browser-extension/suno-prep/manifest.json','utf8'));
 assert.deepEqual(manifest.content_scripts[0].matches,['https://suno.com/*']);
 assert.equal(manifest.permissions,undefined);assert.equal(manifest.host_permissions,undefined);
});
