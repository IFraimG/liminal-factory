import React from 'react';
import {Check,LoaderCircle,UserRound,Workflow} from 'lucide-react';
import type {Task} from '../types';
export const agentNames:Record<string,string>={codex:'GPT · Codex',antigravity:'Gemini · Argon',kimi:'Kimi K3.1 Pro High'};
const shortNames:Record<string,string>={codex:'GPT',antigravity:'Argon',kimi:'Kimi'};
const pretty=(name:string)=>name.replaceAll('_',' ').replace(/\b\w/g,c=>c.toUpperCase());
const music=new Set(['audio_reference','music_brief','music_approval','audio_engineer']);
const visual=new Set(['visual_reference','unity_preview','visual_approval','recording_setup','visual_render','final_assembly']);
export function graphLayout(workflow:Record<string,string[]>){
 const ranks:Record<string,number>={};
 function rank(name:string,trail=new Set<string>()):number{
  if(ranks[name]!==undefined)return ranks[name];
  if(trail.has(name))throw Error('Pipeline dependency cycle');
  const next=new Set(trail);next.add(name);
  return ranks[name]=Math.max(-1,...(workflow[name]||[]).map(parent=>rank(parent,next)))+1;
 }
 return Object.keys(workflow).map(name=>({name,x:30+(music.has(name)?0:visual.has(name)?1:2)*310,y:58+rank(name)*112}));
}
export function PipelineGraph({tasks,workflow,selected,onSelect}:{tasks:Task[];workflow:Record<string,string[]>;selected:string;onSelect:(name:string)=>void}){
 const layout=graphLayout(workflow),positions=Object.fromEntries(layout.map(node=>[node.name,node]));
 const height=Math.max(...layout.map(node=>node.y))+112;
 return <section className="panel pipeline-graph" aria-label="Pipeline dependency graph"><div className="graph-heading"><Workflow size={17}/><h2>Production workflow</h2><span>Choose a step to set agent priority</span></div><div className="graph-scroll" tabIndex={0} aria-label="Scrollable workflow graph"><div className="graph-canvas" style={{height}}>
 {['Music','Unity visuals','Metadata'].map((name,index)=><h3 className="graph-lane" key={name} style={{left:30+index*310}}>{name}</h3>)}
 <svg width="920" height={height} className="graph-edges" aria-hidden="true"><defs><marker id="workflow-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="currentColor"/></marker></defs>{layout.flatMap(target=>(workflow[target.name]||[]).map(parent=>{
  const source=positions[parent];if(!source)return null;
  let path:string;
  if(source.x===target.x)path=`M ${source.x+120} ${source.y+72} V ${target.y}`;
  else {const direction=target.x>source.x?1:-1,startX=source.x+(direction===1?240:0),endX=target.x+(direction===1?0:240),gap=target.y-18;path=`M ${startX} ${source.y+36} H ${startX+direction*18} V ${gap} H ${endX-direction*18} V ${target.y+36} H ${endX}`;}
  return <path key={parent+'-'+target.name} d={path} markerEnd="url(#workflow-arrow)" className={target.name===selected||parent===selected?'edge-selected':''}/>;
 }))}</svg>
 {layout.map(node=>{const task=tasks.find(t=>t.name===node.name);if(!task)return null;return <button key={node.name} className={`graph-node ${selected===node.name?'is-selected':''} ${task.execution_kind==='approval'?'is-gate':''}`} style={{left:node.x,top:node.y}} onClick={()=>onSelect(node.name)} aria-pressed={selected===node.name} aria-label={`${pretty(node.name)} · ${task.status}`}><span className={'task-dot '+task.status.toLowerCase().split(' ')[0]}/><span className="grow"><strong>{pretty(node.name)}</strong><small>{task.status}</small><span className="graph-order">{task.execution_kind==='approval'?'Your approval':task.agent_priorities?.map(p=>shortNames[p]||p).join(' → ')}</span></span>{task.execution_kind==='approval'?<UserRound size={14}/>:['Completed','Approved'].includes(task.status)?<Check size={14}/>:task.status==='Running'?<LoaderCircle size={14} className="spin"/>:null}</button>})}
 </div></div><p className="graph-caption">Arrows show dependencies. Dashed steps require your approval. Agent order is independent for every executable step.</p></section>;
}
