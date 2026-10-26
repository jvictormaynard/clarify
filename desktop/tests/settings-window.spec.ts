import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createContext, runInContext } from 'node:vm';
import { resolve } from 'node:path';
import { test } from '@playwright/test';
import { transformWithOxc } from 'vite';
import { formatUsageReset, usageProgress } from '../../shared/usage';

// Render the real page functions with isolated hooks and neutral control nodes.
// These tests check operation ownership; the browser suite owns DOM acceptance.
async function pageHarness(file, name, controller) {
 const slots=[];let index=0;const effects=[];
 const node=(type,props,...children)=>({type,props:{...props,children}});
 const symbols=['Button','Confirm','Input','HistoryEntryActions','HistoryComparison','Field','Section','AccountSignIn','ChevronRight','Gauge','LogIn','RefreshCw','TriangleAlert','UserRound','Cloud','HardDrive','History','LoaderCircle','Monitor','Smartphone','Trash2'];
 const context=createContext({controller, jsx:node,Fragment:'Fragment',...Object.fromEntries(symbols.map(x=>[x,x])),
   t:x=>x,uiLanguage:'en',usageProgress,formatUsageReset,
   useState:initial=>{const slot=index++;if(!(slot in slots))slots[slot]=initial;return [slots[slot],value=>{slots[slot]=typeof value==='function'?value(slots[slot]):value;}];},
   useRef:initial=>{const slot=index++;if(!(slot in slots))slots[slot]={current:initial};return slots[slot];},
   useEffect:(fn,deps)=>{const slot=index++;const before=slots[slot];if(!before || deps.some((x,i)=>x!==before.deps[i])){slots[slot]={deps};effects.push(fn);}},
   getHistoryPage:async context=>({context,revision:'1',entries:[{id:'row',text:'saved',timestamp:1,sourceDevice:'desktop',truncated:false}],cursor:''}),
 });
 const source=readFileSync(resolve('src',file),'utf8').replace(/^import\b[\s\S]*?;\s*/gm,'').replace(/^export /gm,'');
 const compiled=await transformWithOxc(source,file,{lang:'tsx',jsx:{runtime:'classic',pragma:'jsx',pragmaFrag:'Fragment'}});
 runInContext(compiled.code,context);
 return {render(){index=0;const tree=runInContext(`${name}({controller})`,context);for(const effect of effects.splice(0))effect();return tree;}};
}
function find(tree, predicate) {
 if(Array.isArray(tree))return tree.flatMap(item=>find(item,predicate));
 if(!tree || typeof tree!=='object')return [];
 return [...(predicate(tree)?[tree]:[]),...find(tree.props?.children,predicate)];
}
const flush=async()=>{for(let i=0;i<20;i++)await Promise.resolve();};
const account={endpoint:'https://example.test',email:'',signedIn:false,busy:false,pending:'',usage:{}};

test('Account Continue ignores unrelated global busy and respects its own operation', async () => {
 const controller={state:{accountState:account},run:async()=>true,dirty:false,busy:true,accountPending:false};
 const h=await pageHarness('pages/account-page.tsx','AccountPage',controller);let tree=h.render();
 assert.equal(find(tree,x=>x.type==='AccountSignIn')[0].props.busy,false);
 assert.equal(find(tree,x=>x.type==='fieldset')[0].props.disabled,false);
 controller.accountPending=true;tree=h.render();assert.equal(find(tree,x=>x.type==='AccountSignIn')[0].props.busy,true);assert.equal(find(tree,x=>x.type==='fieldset')[0].props.disabled,true);
 controller.accountPending=false;controller.dirty=true;tree=h.render();assert.equal(find(tree,x=>x.type==='fieldset')[0].props.disabled,true);
});

test('History Cancel ignores global busy; only its own deletion prevents repeat or dismissal', async () => {
 let release;const gate=new Promise(r=>release=r);let calls=0;
 const controller={state:{historyState:{context:'guest',revision:'1'}},busy:true,run:async()=>{calls++;await gate;return true;}};
 const h=await pageHarness('pages/history-page.tsx','HistoryPage',controller);h.render();await flush();let tree=h.render();
 find(tree,x=>x.props?.['aria-label']==='Excluir transcrição')[0].props.onClick();tree=h.render();
 let confirm=find(tree,x=>x.type==='Confirm')[0];let buttons=find(confirm,x=>x.type==='Button');
 assert.equal(buttons[0].props.disabled,false);assert.equal(buttons[1].props.disabled,false);
 buttons[1].props.onClick();buttons[1].props.onClick();tree=h.render();confirm=find(tree,x=>x.type==='Confirm')[0];buttons=find(confirm,x=>x.type==='Button');
 assert.equal(calls,1);assert.equal(buttons[0].props.disabled,true);assert.equal(buttons[1].props.disabled,true);
 confirm.props.onOpenChange(false);tree=h.render();assert.equal(find(tree,x=>x.type==='Confirm')[0].props.open,true);
 release();await flush();tree=h.render();assert.equal(find(tree,x=>x.type==='Confirm')[0].props.open,false);
});


test('Account confirmation Cancel stays available for unrelated busy state and drafts', async () => {
 const controller={state:{accountState:{...account,signedIn:true}},run:async()=>true,dirty:false,busy:true,accountPending:false};
 const h=await pageHarness('pages/account-page.tsx','AccountPage',controller);let tree=h.render();
 find(tree,x=>x.type==='Button' && x.props.children.includes('Sair da conta'))[0].props.onClick();tree=h.render();
 let confirmation=find(tree,x=>x.type==='Confirm')[0];assert.equal(confirmation.props.open,true);assert.equal(find(confirmation,x=>x.type==='Button')[0].props.disabled,false);
 controller.dirty=true;tree=h.render();confirmation=find(tree,x=>x.type==='Confirm')[0];assert.equal(find(confirmation,x=>x.type==='Button')[0].props.disabled,false);assert.equal(find(confirmation,x=>x.type==='Button')[1].props.disabled,true);
 controller.dirty=false;controller.accountPending=true;controller.state.accountState.busy=true;tree=h.render();confirmation=find(tree,x=>x.type==='Confirm')[0];assert.equal(find(confirmation,x=>x.type==='Button')[0].props.disabled,false);assert.equal(find(confirmation,x=>x.type==='Button')[1].props.disabled,true);
 confirmation.props.onOpenChange(false);tree=h.render();assert.equal(find(tree,x=>x.type==='Confirm')[0].props.open,false);
});


test('Account destructive submission alone blocks dismissal and duplicate confirmation', async () => {
 let release;const gate=new Promise(resolve=>release=resolve);let calls=0;
 const controller={state:{accountState:{...account,signedIn:true}},run:async()=>{calls++;await gate;return true;},dirty:false,busy:false,accountPending:false};
 const h=await pageHarness('pages/account-page.tsx','AccountPage',controller);let tree=h.render();
 find(tree,x=>x.type==='Button' && x.props.children.includes('Sair da conta'))[0].props.onClick();tree=h.render();
 let confirmation=find(tree,x=>x.type==='Confirm')[0];const submit=find(confirmation,x=>x.type==='Button')[1];
 submit.props.onClick();submit.props.onClick();tree=h.render();confirmation=find(tree,x=>x.type==='Confirm')[0];
 assert.equal(calls,1);assert.equal(find(confirmation,x=>x.type==='Button')[0].props.disabled,true);
 confirmation.props.onOpenChange(false);tree=h.render();assert.equal(find(tree,x=>x.type==='Confirm')[0].props.open,true);
 release();await flush();tree=h.render();assert.equal(find(tree,x=>x.type==='Confirm')[0].props.open,false);
});


test('Account social cancellation remains available during active login and local drafts', async () => {
 const calls=[];
 const controller={state:{accountState:{...account,busy:true,socialPending:true}},run:async(...args)=>{calls.push(args);return true;},dirty:true,busy:true,accountPending:false};
 const h=await pageHarness('pages/account-page.tsx','AccountPage',controller);const tree=h.render();
 const cancel=find(tree,x=>x.type==='Button' && x.props.children.includes('Cancelar login'))[0];
 assert.notEqual(cancel.props.disabled,true);cancel.props.onClick();await flush();
 assert.deepEqual(calls.map(args=>Array.from(args)),[['accountCommand','cancel-social','']]);
});
