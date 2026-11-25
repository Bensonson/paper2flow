// Execute generated report JavaScript with a minimal DOM; this is not visual browser QA.
// Called by check_report_defaults.py; no installed packages or network are used.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const path=require('node:path');
if(!process.argv[2])throw new Error('Usage: node check_report_defaults.js REPORT.html');
const html=fs.readFileSync(path.resolve(process.argv[2]),'utf8');
const ids=new Map(),blobs=[],requests=[],downloads=[];
class Element {
  constructor(tag='div'){this.tagName=tag.toUpperCase();this.children=[];this.parentNode=null;this.attrs={};this.dataset={};this.style={setProperty:(k,v)=>this.style[k]=v};this.handlers={};this.className='';this._text='';this.value='';this.files=[];this.clientWidth=900;this.clientHeight=600;this.offsetHeight=114;this.hidden=false;this.disabled=false;this._id='';}
  set id(v){this._id=v;ids.set(v,this)} get id(){return this._id}
  set textContent(v){this._text=String(v);this.children=[]} get textContent(){return this._text+this.children.map(n=>n.textContent).join('')}
  get childElementCount(){return this.children.length}
  append(...nodes){for(const node of nodes){node.parentNode=this;this.children.push(node)}}
  replaceChildren(...nodes){this.children=[];this._text='';this.append(...nodes)}
  after(node){if(this.parentNode){const p=this.parentNode,i=p.children.indexOf(this);node.parentNode=p;p.children.splice(i+1,0,node)}}
  remove(){if(this.parentNode)this.parentNode.children=this.parentNode.children.filter(n=>n!==this)}
  setAttribute(k,v){this.attrs[k]=String(v);if(k==='id')this.id=v;if(k==='class')this.className=v}
  getAttribute(k){return this.attrs[k]??null}
  addEventListener(k,fn,options){(this.handlers[k]??=[]).push(fn)}
  async dispatch(k,event={}){Object.assign(event,{target:event.target??this,preventDefault(){this.prevented=true},stopPropagation(){}});for(const f of this.handlers[k]??[])await f(event);return event}
  click(){if(this.tagName==='A')downloads.push({href:this.href,download:this.download});return this.dispatch('click')}
  focus(){} setPointerCapture(id){this.capture=id} releasePointerCapture(){} scrollIntoView(){}
  getBoundingClientRect(){return {left:0,top:0,width:this.clientWidth,height:this.clientHeight,right:this.clientWidth,bottom:this.clientHeight}}
  closest(sel){if(sel==='button'&&this.tagName==='BUTTON')return this;if(sel.startsWith('.')&&this.className.split(' ').includes(sel.slice(1)))return this;return this.parentNode?.closest(sel)??null}
  get classList(){return {add:(...ns)=>this.className=[...new Set([...this.className.split(' '),...ns])].join(' '),remove:(...ns)=>this.className=this.className.split(' ').filter(n=>!ns.includes(n)).join(' '),toggle:(n,v)=>{if(v===undefined)v=!this.className.split(' ').includes(n);v?this.classList.add(n):this.classList.remove(n);return v},contains:n=>this.className.split(' ').includes(n)}}
  querySelectorAll(sel){return all(this).filter(n=>sel.startsWith('.')&&n.classList.contains(sel.slice(1)))}
}
function all(root){return root.children.flatMap(n=>[n,...all(n)])}
const document={body:new Element('body'),documentElement:new Element('html'),title:'',createElement:t=>new Element(t),createElementNS:(ns,t)=>new Element(t),createTextNode:s=>{const e=new Element('#text');e.textContent=s;return e},getElementById:id=>ids.get(id)??null,querySelectorAll(sel){if(sel==='input[name="agent-pdf-mode"]')return [mode];return []},querySelector(sel){if(sel==='input[name="agent-pdf-mode"]:checked')return mode;return null}};
for(const m of html.matchAll(/<[^>]*\bid="([^"]+)"[^>]*>/g)){const e=new Element(m[0].match(/^<(\w+)/)[1]);e.id=m[1];document.body.append(e)}
for(const m of html.matchAll(/<script\b[^>]*\bid="([^"]+)"[^>]*>([\s\S]*?)<\/script>/g))ids.get(m[1]).textContent=m[2];
const mode=new Element('input');mode.value='path';
if(ids.has('agent-url'))ids.get('agent-url').value='http://127.0.0.1:9999';
const nativeURL=URL;class CapturedURL extends nativeURL{static createObjectURL(blob){blobs.push(blob);return 'blob:qa-'+blobs.length}static revokeObjectURL(){}}
const window={addEventListener(){},matchMedia:()=>({matches:false}),print(){},location:{protocol:'file:',origin:'null'}};
const timers=new Map();let timer=0;
const context={document,window,Node:Element,URL:CapturedURL,Blob,AbortController,DOMException,console,localStorage:{getItem:()=>null,setItem(){}},setTimeout:(f,ms)=>{const id=++timer;if(ms===1000)Promise.resolve().then(f);else timers.set(id,f);return id},clearTimeout:id=>timers.delete(id),requestAnimationFrame:f=>f(),ResizeObserver:class{observe(){}},fetch:async(url,opts={})=>{if(url.endsWith('/ask')){requests.push(JSON.parse(opts.body));return {ok:true,json:async()=>({job_id:'job'})}}if(url.includes('/jobs/'))return {ok:true,json:async()=>({status:'completed',answer:'Synthetic answer [page 1]'})};return {ok:true,json:async()=>({ready:true,agent:'codex'})}}};
context.globalThis=context;
let scripts=[...html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/g)].filter(m=>!m[1].includes('application/json')).map(m=>m[2]);
assert.equal(scripts.length,1,'Offline report should have one active script');
const hook=`globalThis.qa={get state(){return {data,language,steps,selectedId,transform:{...transform},failure}},selectStep,renderAll,computeLineage,lineageColors,lineageGradient,askAgent,currentConversation,updateAgentUI,setConnection(){bridgeConnection={url:'http://127.0.0.1:9999',token:'qa-only'};connectPhase='connected';updateAgentUI();}};`;
scripts[0]=scripts[0].replace(/renderAll\(\);\s*\}\)\(\);\s*$/,`renderAll();${hook}})();`);
vm.createContext(context);vm.runInContext(scripts[0],context,{filename:'fresh-report-runtime.js'});
const q=context.qa;
async function main(){
 assert(q,'QA hook inserted');assert.equal(q.state.failure,null);assert.equal(q.state.language,'en');assert.equal(document.documentElement.lang,'en');
 if(path.basename(process.argv[2])==='english-only.html'){assert.equal(ids.get('language-button').disabled,true);assert.match(ids.get('language-button').title,/unavailable|not been supplied/i);console.log(JSON.stringify({passed:true,checks:['English-only report disables missing translation with an explicit unavailable cue']}));return;}
 assert.match(ids.get('paper-title').textContent,/English Original/);assert.match(ids.get('detail-panel').textContent,/English task/);assert.match(ids.get('print-steps').textContent,/English caveat|English task/);
 q.selectStep('merge');await ids.get('language-button').dispatch('click');assert.equal(q.state.language,'zh');assert.equal(q.state.selectedId,'merge');
 for(const text of ['中文任务','中文输入','中文输出','中文参数','中文设置','中文发现','中文先决原因'])assert(ids.get('detail-panel').textContent.includes(text),text+' must switch');
 assert.match(ids.get('paper-summary').textContent,/中文概要/);assert.match(ids.get('notes-list').textContent,/中文限制说明/);assert.match(ids.get('print-steps').textContent,/中文任务/);
 await ids.get('download-button').dispatch('click');const exported=JSON.parse(await blobs.at(-1).text());assert.match(exported.steps[2].task,/中文任务/);assert.equal(exported.source.sha256,q.state.data.source.sha256);
 ids.get('agent-question').value='中文提问';await ids.get('agent-export').dispatch('click');const requestExport=JSON.parse(await blobs.at(-1).text());assert.match(requestExport.workflow.steps[2].task,/中文任务/);
 q.setConnection();await q.askAgent({preventDefault(){}});assert.equal(requests.at(-1).node_id,'merge');assert.match(requests.at(-1).workflow.steps[2].task,/中文任务/);assert.equal(requests.at(-1).history.length,0);
 ids.get('agent-question').value='Follow-up question';await q.askAgent({preventDefault(){}},true);assert.equal(requests.at(-1).history.length,1);assert.equal(q.currentConversation().length,2);
 q.selectStep('compare');assert.equal(q.currentConversation().length,0);assert.equal(ids.get('agent-followup').disabled,true);q.selectStep('merge');await ids.get('language-button').dispatch('click');assert.equal(q.currentConversation().length,2);assert.match(ids.get('detail-panel').textContent,/English task/);
 ids.get('agent-question').value='New topic';await q.askAgent({preventDefault(){}});assert.equal(requests.at(-1).history.length,0);assert.equal(q.currentConversation().length,1);
 const successfulFetch=context.fetch;context.fetch=async(url,opts)=>url.includes('/jobs/')?{ok:true,json:async()=>({status:'error',error:'Synthetic failure'})}:successfulFetch(url,opts);ids.get('agent-question').value='Failed follow-up';await q.askAgent({preventDefault(){}},true);assert.equal(q.currentConversation().length,1,'Failed followup preserves successful history');context.fetch=successfulFetch;
 const viewport=ids.get('graph-viewport');let before=q.state.transform;const e=await viewport.dispatch('wheel',{deltaMode:0,deltaX:0,deltaY:120,shiftKey:false,clientX:400,clientY:300});assert(e.prevented);assert(Math.abs(q.state.transform.scale/before.scale-1)<.05);
 before=q.state.transform;await viewport.dispatch('wheel',{deltaMode:0,deltaX:37,deltaY:0,shiftKey:false,clientX:400,clientY:300});assert.equal(q.state.transform.x,before.x-37);assert.equal(q.state.transform.scale,before.scale);
 before=q.state.transform;await viewport.dispatch('wheel',{deltaMode:1,deltaX:0,deltaY:2,shiftKey:true});assert.equal(q.state.transform.x,before.x-32);
 before=q.state.transform;await viewport.dispatch('wheel',{deltaMode:2,deltaX:0,deltaY:-1,shiftKey:false,clientX:400,clientY:300});assert(Math.abs(q.state.transform.scale/before.scale-1)<.05);before=q.state.transform;
 const pointer=await viewport.dispatch('pointerdown',{button:0,pointerId:2,clientX:10,clientY:10});assert(pointer.prevented);await viewport.dispatch('pointermove',{pointerId:2,clientX:40,clientY:60});assert.equal(q.state.transform.x,before.x+30);assert.equal(q.state.transform.y,before.y+50);await viewport.dispatch('pointerup');
 for(const cancel of ['pointercancel','lostpointercapture']){await viewport.dispatch('pointerdown',{button:0,pointerId:2,clientX:0,clientY:0});await viewport.dispatch(cancel);before=q.state.transform;await viewport.dispatch('pointermove',{pointerId:2,clientX:50,clientY:50});assert.deepEqual(q.state.transform,before,'No stuck drag after '+cancel);}
 for(const count of [1,2,3,4,5,6,100]){const roots=Array.from({length:count},(_,i)=>'root-'+String(i).padStart(3,'0')),relations=new Map(roots.map(id=>[id,[]]));relations.set('merge',roots);relations.set('next',['merge']);const lineage=q.computeLineage([...roots,'merge','next'],relations),colors=q.lineageColors(lineage,'next');assert.equal(colors.length,count);assert.equal(new Set(colors).size,count);if(count>1){const defs=new Element('defs');q.lineageGradient(defs,'qa-gradient',colors,{});assert.equal(defs.children[0].children.length,count);assert.equal(defs.children[0].children[0].attrs.offset,'0%');assert.equal(defs.children[0].children.at(-1).attrs.offset,'100%');}}
 const diamond=q.computeLineage(['a','b','ac','bc','merge','next'],new Map([['a',[]],['b',[]],['ac',['a']],['bc',['a','b']],['merge',['ac','bc']],['next',['merge']]]));assert.equal(q.lineageColors(diamond,'next').length,2,'Repeated source origin deduplicates through branch/merge');
 const edgePaths=all(ids.get('edge-layer')).filter(e=>e.tagName==='PATH'&&e.style.stroke);assert.equal(edgePaths.length,3,'Three rendered edges exist');const strokes=edgePaths.map(e=>e.style.stroke);assert.equal(strokes[0],'#3585bf');assert.equal(strokes[1],'#d88b31');assert.match(strokes[2],/^url\(#lineage-edge-/);q.selectStep('compare');await ids.get('theme-button').dispatch('click');assert.deepEqual(edgePaths.map(e=>e.style.stroke),strokes,'Selection and theme preserve rendered inline source colors');
 console.log(JSON.stringify({passed:true,kind:'VM DOM integration (not visual browser QA)',checks:['full body and print translation','JSON and request export language','active language in ask context','node-isolated followups, new topics and failed followup retention','gentle pixel/line/page zoom and horizontal/Shift pan','selection-preventing drag and release/cancel/lostcapture','1-100 distinct lineage colors/gradient stops and deduplicated origins','rendered edge source colors stable on selection/theme']}));
}
main().catch(e=>{console.error(e.stack);process.exitCode=1});
