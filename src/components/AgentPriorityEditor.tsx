import React,{useEffect,useState} from 'react';
import {ChevronUp,ChevronDown,LockKeyhole} from 'lucide-react';
import type {Task} from '../types';
import {agentNames} from './PipelineGraph';
import {api} from '../stores/api';
const active=new Set(['Running','Waiting for Client','Waiting for CLI','Waiting for Permission','Waiting for quota']);
export function AgentPriorityEditor({episode,task,busy,onSave}:{episode:string;task:Task;busy:boolean;onSave:()=>Promise<void>}){
 const saved=task.agent_priorities||[],signature=saved.join(','),locked=task.priority_locked||active.has(task.status);
 const [draft,setDraft]=useState(saved),[saving,setSaving]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState('');
 useEffect(()=>{setDraft(saved);setError('')},[task.name,signature,locked]);
 useEffect(()=>setNotice(''),[task.name]);
 if(task.execution_kind==='approval')return <div className="priority-editor"><p>This step is your manual approval. Select its upstream production step to change the AI agents.</p></div>;
 function move(index:number,direction:number){setDraft(current=>{const next=[...current];[next[index],next[index+direction]]=[next[index+direction],next[index]];return next});setNotice('');}
 const disabled=locked||busy||saving,changed=draft.join(',')!==signature;
 return <div className="priority-editor"><div className="priority-heading"><h3>Agent priority · this step</h3>{locked&&<span><LockKeyhole size={13}/> Locked while active</span>}</div><p className="muted small">The first eligible agent is selected: at least 5% remaining, or Argon with unknown quota. Known balances below 5% and unknown GPT/Kimi balances are skipped.{task.execution_kind==='assisted_local'?' The selected AI prepares a check plan; local tools then execute this step.':''}</p>
 <ol className="priority-list">{draft.map((provider,index)=><li key={provider}><span className="priority-rank">{index+1}</span><strong>{agentNames[provider]||provider}</strong><button type="button" aria-label={`Move ${agentNames[provider]} up`} disabled={disabled||index===0} onClick={()=>move(index,-1)}><ChevronUp size={14}/></button><button type="button" aria-label={`Move ${agentNames[provider]} down`} disabled={disabled||index===draft.length-1} onClick={()=>move(index,1)}><ChevronDown size={14}/></button></li>)}</ol>
 <div className="row"><button className="primary" disabled={disabled||!changed} onClick={async()=>{setSaving(true);setError('');try{await api(`/episodes/${episode}/tasks/${task.name}/priorities`,'PUT',{order:draft});await onSave();setNotice('Saved for the next run. Existing outputs were kept.')}catch(e){setError(e instanceof Error?e.message:String(e));try{await onSave()}catch{}}finally{setSaving(false)}}}>Save agent priority</button>{changed&&!locked&&<small className="muted">Unsaved order</small>}</div>
 {locked&&<p role="status" className="muted small">Stop this step with Cancel Task before editing. Waiting for quota, CLI or a permission still counts as active.</p>}{typeof task.data.selected_provider==='string'&&<p className="small">Selected agent: {agentNames[String(task.data.selected_provider)]||String(task.data.selected_provider)}</p>}{error&&<p role="alert" className="error-text">{error}</p>}{notice&&<p role="status" className="success-text">{notice}</p>}
 </div>;
}
