import { readFileSync } from 'node:fs';
import { stripTypeScriptTypes } from 'node:module';
import { createContext, runInContext } from 'node:vm';
import assert from 'node:assert/strict';
import { resolve } from 'node:path';
import { test } from '@playwright/test';

// The scheduler runs native-window effects with stable hooks. Polling effects
// stay off; browser tests cover React DOM and the application effect lifecycle.
// Every bridge response uses an isolated in-memory repository.
const root=resolve('..');
const clone=x=>structuredClone(x);
function setup() {
  const routes=Object.fromEntries(['transcription','refinement','rewrite','translation','local_asr_refinement'].map(scope=>[scope,{prompt:`saved-${scope}`,model:'model',endpoint:'',enabled:true}]));
  let persisted={routes:clone(routes),historyRetentionDays:null,recordingControls:{max_duration_seconds:null,warning_seconds:5,vad:{enabled:false,level_threshold:0.05,minimum_speech_seconds:0.1,silence_duration_seconds:0.5}},snippets:[{trigger:'sig',replacement:'saved text',enabled:true,case_sensitive:false}],dictionaryEntries:[{term:'original',pronunciation:'',aliases:[],enabled:true}]};
  let staged=clone(persisted);
  let selectedScope='transcription', microphoneTestBusy=false, selectedProviderId='cloud', snippetContext='guest',localProfileIndex=0,localDeviceIndex=0;
  const keys={cloud:true,groq:true};
  let accountState={busy:false,signedIn:false,socialPending:false};
  const snapshot=()=>({...clone(staged),routePrompt:staged.routes[selectedScope].prompt,routeModelId:staged.routes[selectedScope].model,routeCustomEndpoint:staged.routes[selectedScope].endpoint,routeEnabled:staged.routes[selectedScope].enabled,selectedScope,microphoneTestBusy,providerBaseUrl:'',providerDirty:false,dirty:false,accountState:clone(accountState),snippetContext,uiLanguage:'en',selectedProviderId,localProfileIndex,localDeviceIndex,providerHasApiKey:keys[selectedProviderId],providers:[{id:'cloud'}]});
  const records=[]; const slots=[]; let index=0;
  let nativeCloses=0, closeListener; const effects=[];
  const windowEffect=(fn,deps)=>{const slot=index++;const previous=slots[slot];if(!previous || deps.some((x,i)=>!Object.is(x,previous.deps[i]))){slots[slot]={deps,cleanup:previous?.cleanup};effects.push(()=>{previous?.cleanup?.();slots[slot].cleanup=fn();});}};
  let gate=null; let failure=null;let afterPreference=null;
  const invoke=async(_,request)=>{
    const {method,args}=request;records.push(clone(request));
    if(gate?.method===method){const local=gate;gate=null;local.started();await local.wait;}
    if(failure?.method===method){const error=failure.error;failure=null;throw error;}
    if(method==='selectProvider') selectedProviderId=args[0];
    if(method==='selectLocalProfile')localProfileIndex=args[0];
    if(method==='selectLocalDevice')localDeviceIndex=args[0];
    if(method==='clearProvider') keys[selectedProviderId]=false;
    if(method==='selectWorkflow') selectedScope=args[0];
    if(method==='setRoutePrompt') staged.routes[selectedScope].prompt=args[0];
    if(method==='setRouteModelId') staged.routes[selectedScope].model=args[0];
    if(method==='setRouteCustomEndpoint') staged.routes[selectedScope].endpoint=args[0];
    if(method==='setHistoryRetentionDays') staged.historyRetentionDays=args[0];
    if(method==='setRecordingControls') staged.recordingControls=clone(args[0]);
    if(method==='setDictionaryEntries') {if(args[1]!==undefined)assert.equal(args[1],snippetContext,'dictionary context');if(args[2]!==undefined)assert.deepEqual(clone(args[2]),persisted.dictionaryEntries,'dictionary snapshot changed');staged.dictionaryEntries=clone(args[0]);}
    if(method==='setSnippets') {assert.equal(args[1],snippetContext);if(args[2]!==undefined)assert.deepEqual(clone(args[2]),persisted.snippets,'snippet snapshot changed');staged.snippets=clone(args[0]);}
    if(method==='save') {if(args[0]!==undefined)assert.equal(args[0],snippetContext,'commit context');persisted=clone(staged);}
    if(method==='load') staged=clone(persisted);
    if(method==='testMicrophone') microphoneTestBusy=true;
    if(method==='stopMicrophoneTest') microphoneTestBusy=false;
    if(method==='savePreference') {
      const [setter,[value]]=args;
      if(setter==='setRecordingVadEnabled') {persisted.recordingControls.vad.enabled=value;staged.recordingControls.vad.enabled=value;}
      else if(setter==='setLanguage') {persisted.language=value;staged.language=value;}
      else if(setter==='setRouteModelId') {persisted.routes[selectedScope].model=value;staged.routes[selectedScope].model=value;}
    }
    if(method==='saveLibraryPreference') {
      const [library,identity,field,value,context]=args;
      assert.equal(context,snippetContext);
      const key=library==='dictionary'?'dictionaryEntries':'snippets';
      const pos=persisted[key].findIndex(entry=>JSON.stringify(entry)===JSON.stringify(identity));
      assert.ok(pos>=0,'stale identity');
      persisted[key][pos][field]=value;staged[key][pos][field]=value;
      const sync=afterPreference;afterPreference=null;sync?.();
    }
    return snapshot();
  };
  const context=createContext({ windowEffect, isTauri:()=>true,getCurrentWindow:()=>({close:async()=>{nativeCloses++;},onCloseRequested:async fn=>{closeListener=fn;return ()=>{};}}), TextEncoder, t:x=>x,setUiLanguage:()=>{},recordingDraft:x=>({maximum:x.max_duration_seconds===null?'':String(x.max_duration_seconds),warning:String(x.warning_seconds),enabled:x.vad.enabled,threshold:String(x.vad.level_threshold),speech:String(x.vad.minimum_speech_seconds),silence:String(x.vad.silence_duration_seconds)}),recordingValue:x=>({max_duration_seconds:x.maximum===''?null:Number(x.maximum),warning_seconds:Number(x.warning),vad:{enabled:x.enabled,level_threshold:Number(x.threshold),minimum_speech_seconds:Number(x.speech),silence_duration_seconds:Number(x.silence)}}),invoke,
    useState:initial=>{const slot=index++;if(!(slot in slots)){slots[slot]={value:slot===0?snapshot():initial};slots[slot].set=value=>{slots[slot].value=typeof value==='function'?value(slots[slot].value):value;};}return [slots[slot].value,slots[slot].set];},
    useRef:value=>{const slot=index++;if(!(slot in slots))slots[slot]={current:value};return slots[slot];},
    useMemo:fn=>fn(),useCallback:(fn,deps)=>{const slot=index++;const previous=slots[slot];if(!previous || deps.some((x,i)=>!Object.is(x,previous.deps[i])))slots[slot]={fn,deps};return slots[slot].fn;},useEffect:()=>{},
  });
  for(const file of ['bridge.ts','state.ts','use-settings-window.ts','use-settings.ts']){
    const sourceRoot = root;
    let source=readFileSync(`${sourceRoot}/desktop/src/settings/${file}`,'utf8').replace(/^import\b[\s\S]*?;\s*/gm,'').replace(/^export /gm,'');
    if(file==='use-settings-window.ts') source=source.replace(/\buseEffect\(/g,'windowEffect(');
    runInContext(stripTypeScriptTypes(source),context);
  }
  return {render(){index=0;const c=runInContext('useSettings()',context);for(const effect of effects.splice(0))effect();return c;}, records, get persisted(){return persisted;}, get keys(){return keys;}, get nativeCloses(){return nativeCloses;},
    setAccountState(value){accountState={...accountState,...value};},
    replaceLibrary(library,entries){const key=library==='dictionary'?'dictionaryEntries':'snippets';persisted[key]=clone(entries);staged[key]=clone(entries);},
    syncAfterPreference(library,entries){afterPreference=()=>{const key=library==='dictionary'?'dictionaryEntries':'snippets';persisted[key]=clone(entries);staged[key]=clone(entries);};},
    close(){let prevented=false;closeListener({preventDefault(){prevented=true;}});return prevented;}, changeContext(value){snippetContext=value;}, poll(){return runInContext('pollSettings()',context);},
    pause(method){let release,started;const wait=new Promise(r=>release=r);const beginning=new Promise(r=>started=r);gate={method,wait,started};return {release,started:beginning};},
    fail(method,error){failure={method,error};},
  };
}
test('save captures its revision; typing and navigation stay responsive', async () => {
 const h=setup();let c=h.render();await c.navigate('text');c=h.render();c.setPrompt('save-me');c=h.render();
 const gate=h.pause('save');const saving=c.save();await gate.started;
 c=h.render();c.setPrompt('newer-text');const nav=c.navigate('dictionary');c=h.render();assert.equal(c.page,'dictionary');assert.equal(c.routeLoading,false);
 const back=c.navigate('text');c=h.render();assert.equal(c.page,'text');gate.release();await Promise.all([saving,nav,back]);c=h.render();
 assert.equal(h.persisted.routes.refinement.prompt,'save-me');assert.equal(c.prompt,'newer-text');assert.equal(c.dirty,true);assert.equal(c.pageDirty,true);
 await c.save();c=h.render();assert.equal(h.persisted.routes.refinement.prompt,'newer-text');assert.equal(c.dirty,false);

});

test('contextual save preserves drafts on other pages', async () => {
 const h=setup();let c=h.render();await c.navigate('text');c=h.render();c.setPrompt('keep route draft');c.setSnippets([{trigger:'draft',replacement:'pending',enabled:true,case_sensitive:false}]);await c.navigate('general');c=h.render();c.setRetention('30');c=h.render();await c.save();c=h.render();
 assert.equal(h.persisted.historyRetentionDays,30);assert.equal(h.persisted.routes.refinement.prompt,'saved-refinement');assert.equal(h.persisted.snippets[0].trigger,'sig');assert.equal(c.snippets[0].trigger,'draft');assert.equal(c.pageDirty,false);assert.equal(c.dirty,true);
 await c.navigate('text');c=h.render();assert.equal(c.prompt,'keep route draft');

});

test('latest route wins and hidden microphone test stops', async () => {
 const h=setup();let c=h.render();const gate=h.pause('testMicrophone');const test=c.run('testMicrophone');await gate.started;
 const one=c.navigate('text','rewrite');const two=c.navigate('dictionary');const three=c.navigate('text','refinement');c=h.render();assert.equal(c.page,'text');
 gate.release();await Promise.all([test,one,two,three]);c=h.render();assert.equal(c.state.selectedScope,'refinement');assert.equal(c.state.microphoneTestBusy,false);assert.equal(c.routeLoading,false);assert.equal(h.records.some(x=>x.method==='save'),false);

});

test('library flag persists only the original saved row flag', async () => {
 const h=setup();let c=h.render();await c.navigate('text');c=h.render();c.setPrompt('must survive');await c.navigate('dictionary');c=h.render();c.setDictionary([{...c.state.dictionaryEntries[0],term:'edited draft'}]);c=h.render();
 await c.setLibraryPreference('dictionary',0,'enabled',false);c=h.render();assert.equal(h.persisted.dictionaryEntries[0].enabled,false);assert.equal(h.persisted.dictionaryEntries[0].term,'original');assert.equal(c.dictionary[0].term,'edited draft');assert.equal(c.dictionary[0].enabled,false);
 await c.save();c=h.render();assert.equal(h.persisted.dictionaryEntries[0].term,'edited draft');assert.equal(h.persisted.routes.refinement.prompt,'saved-refinement');

});

test('consecutive library preferences use updated saved identity', async () => {
 const h=setup();let c=h.render();await c.navigate('snippets');c=h.render();const gate=h.pause('saveLibraryPreference');const a=c.setLibraryPreference('snippets',0,'enabled',false);await gate.started;const b=c.setLibraryPreference('snippets',0,'case_sensitive',true);gate.release();await Promise.all([a,b]);c=h.render();assert.equal(c.error,'');assert.equal(h.persisted.snippets[0].enabled,false);assert.equal(h.persisted.snippets[0].case_sensitive,true);assert.equal(c.dirty,false);

});

test('failed staging cannot leak into another page save', async () => {
 const h=setup();let c=h.render();await c.navigate('text');c=h.render();c.setPrompt('failed prompt');c=h.render();h.fail('save',new Error('disk failure'));assert.equal(await c.save(),false);c=h.render();assert.equal(c.prompt,'failed prompt');assert.match(c.error,/disk failure/);
 await c.navigate('general');c=h.render();c.setRetention('40');c=h.render();await c.save();assert.equal(h.persisted.routes.refinement.prompt,'saved-refinement');assert.equal(h.persisted.historyRetentionDays,40);

});

test('contextual discard preserves drafts on other pages', async () => {
 const h=setup();let c=h.render();await c.navigate('text');c=h.render();c.setPrompt('keep me');await c.navigate('general');c=h.render();c.setRetention('30');c=h.render();await c.discardAndClose();c=h.render();assert.equal(c.retention,'');await c.navigate('text');c=h.render();assert.equal(c.prompt,'keep me');assert.equal(c.dirty,true);

});

test('save all captures drafts across pages and workflows', async () => {
 const h=setup();let c=h.render();
 await c.navigate('text','refinement');c=h.render();c.setPrompt('Review draft');
 await c.navigate('text','rewrite');c=h.render();c.setPrompt('Rewrite draft');
 await c.navigate('general');c=h.render();c.setRetention('45');
 await c.navigate('snippets');c=h.render();c.setSnippets([{trigger:'all',replacement:'Saved together',enabled:true,case_sensitive:false}]);
 c=h.render();c.setClosing(true);c=h.render();await c.saveAndClose();c=h.render();
 assert.equal(h.persisted.routes.refinement.prompt,'Review draft');
 assert.equal(h.persisted.routes.rewrite.prompt,'Rewrite draft');
 assert.equal(h.persisted.historyRetentionDays,45);
 assert.equal(h.persisted.snippets[0].replacement,'Saved together');
 assert.equal(c.dirty,false);
});


test('provider removal rejects the provider captured when confirmation opened', async () => {
 const h=setup();let c=h.render();c.setConfirmAction('clearProvider', 'cloud');c=h.render();
 const gate=h.pause('selectProvider');const selecting=c.selectProvider('groq');await gate.started;
 const removing=c.confirmMutation();gate.release();await Promise.all([selecting,removing]);c=h.render();
 assert.equal(h.keys.cloud,true);assert.equal(h.keys.groq,true);assert.match(c.error,/serviço mudou/);
 assert.equal(h.records.some(x=>x.method==='clearProvider'),false);
});

test('page discard dialog saves only its page and dismisses after success', async () => {
 const h=setup();let c=h.render();await c.navigate('text');c=h.render();c.setPrompt('other page');
 await c.navigate('general');c=h.render();c.setRetention('30');c.setDiscarding(true);c=h.render();await c.saveAndClose();c=h.render();
 assert.equal(h.persisted.historyRetentionDays,30);assert.equal(h.persisted.routes.refinement.prompt,'saved-refinement');
 assert.equal(c.discarding,false);assert.equal(c.dirty,true);
});

for(const library of ['dictionary','snippets']) test(`new ${library} flags edited during Save use the new persisted identity`, async () => {
 const h=setup();let c=h.render();await c.navigate(library);c=h.render();
 if(library==='dictionary')c.setDictionary([...c.state.dictionaryEntries,{term:'new',pronunciation:'',aliases:[],enabled:true}]);
 else c.setSnippets([...c.state.snippets,{trigger:'new',replacement:'text',enabled:true,case_sensitive:false}]);
 c=h.render();const gate=h.pause('save');const saving=c.save();await gate.started;
 const one=c.setLibraryPreference(library,1,'enabled',false);c=h.render();
 const two=library==='snippets'?c.setLibraryPreference(library,1,'case_sensitive',true):Promise.resolve();
 gate.release();await Promise.all([saving,one,two]);c=h.render();await c.save();c=h.render();
 const entries=library==='dictionary'?h.persisted.dictionaryEntries:h.persisted.snippets;
 assert.equal(entries[1].enabled,false);if(library==='snippets')assert.equal(entries[1].case_sensitive,true);assert.equal(c.error,'');
});

test('flag autosave queued during text Save does not restore a deleted row', async () => {
 const h=setup();let c=h.render();await c.navigate('snippets');c=h.render();
 c.setSnippets([...c.state.snippets,{trigger:'new',replacement:'text',enabled:true,case_sensitive:false}]);c=h.render();
 const gate=h.pause('save');const saving=c.save();await gate.started;
 const flag=c.setLibraryPreference('snippets',1,'enabled',false);c=h.render();c.setSnippets([c.snippets[0]]);
 gate.release();await Promise.all([saving,flag]);c=h.render();await c.save();c=h.render();
 assert.equal(h.persisted.snippets.length,1);assert.equal(c.error,'');
});

test('persisted flag queued behind text Save uses its rebound identity', async () => {
 const h=setup();let c=h.render();await c.navigate('snippets');c=h.render();c.setSnippets([{...c.state.snippets[0],replacement:'edited'}]);c=h.render();
 const gate=h.pause('save');const saving=c.save();await gate.started;
 const one=c.setLibraryPreference('snippets',0,'enabled',false);const two=c.setLibraryPreference('snippets',0,'case_sensitive',true);
 gate.release();await Promise.all([saving,one,two]);c=h.render();
 assert.equal(h.persisted.snippets[0].replacement,'edited');assert.equal(h.persisted.snippets[0].enabled,false);assert.equal(h.persisted.snippets[0].case_sensitive,true);assert.equal(c.error,'');
});

test('endpoint-only draft does not restore an older automatic model choice', async () => {
 const h=setup();let c=h.render();await c.navigate('text');c=h.render();c.setRouteOverride({endpoint:'https://example.test/v1'});c=h.render();
 await c.run('setRouteModelId','new-model');c=h.render();await c.save();c=h.render();
 assert.equal(h.persisted.routes.refinement.model,'new-model');assert.equal(h.persisted.routes.refinement.endpoint,'https://example.test/v1');assert.equal(c.error,'');
 assert.equal(h.records.some(x=>x.method==='setRouteModelId'),false);
});

test('dictionary staging rejects a scope change after the frontend check', async () => {
 const h=setup();let c=h.render();await c.navigate('dictionary');c=h.render();c.setDictionary([{...c.state.dictionaryEntries[0],term:'private'}]);c=h.render();
 const gate=h.pause('setDictionaryEntries');const saving=c.save();await gate.started;h.changeContext('other-account');gate.release();assert.equal(await saving,false);
 assert.equal(h.persisted.dictionaryEntries[0].term,'original');
});

test('final commit carries the captured context across an account change', async () => {
 const h=setup();let c=h.render();await c.navigate('dictionary');c=h.render();c.setDictionary([{...c.state.dictionaryEntries[0],term:'private'}]);c=h.render();
 const gate=h.pause('save');const saving=c.save();await gate.started;h.changeContext('other-account');gate.release();assert.equal(await saving,false);
 assert.equal(h.persisted.dictionaryEntries[0].term,'original');
});

test('account submission is guarded while its own queued operation is pending', async () => {
 const h=setup();let c=h.render();const gate=h.pause('accountCommand');const first=c.run('accountCommand','login','one@example.test');await gate.started;
 const second=c.run('accountCommand','login','two@example.test');c=h.render();assert.equal(c.accountPending,true);
 gate.release();await Promise.all([first,second]);c=h.render();assert.equal(c.accountPending,false);assert.equal(h.records.filter(x=>x.method==='accountCommand').length,1);
});

const flush=async()=>{for(let i=0;i<30;i++)await Promise.resolve();};
test('clean close waits for a preference accepted behind a poll', async () => {
 const h=setup();let c=h.render();const gate=h.pause('poll');const poll=h.poll();await gate.started;
 const writing=c.run('setLanguage','pt');assert.equal(h.close(),true);c=h.render();await flush();assert.equal(h.nativeCloses,0);
 gate.release();await Promise.all([poll,writing]);await flush();assert.equal(h.persisted.language,'pt');assert.equal(h.nativeCloses,1);
});

for (const action of ['confirm','undo']) test(`clean close waits for history correction ${action} accepted behind a poll`, async () => {
 const h=setup();let c=h.render();const gate=h.pause('poll');const poll=h.poll();await gate.started;
 const writing=c.runHistoryCorrection(action,{token:'isolated-token'});assert.equal(h.close(),true);c=h.render();await flush();assert.equal(h.nativeCloses,0);
 gate.release();await Promise.all([poll,writing]);await flush();assert.equal(h.records.filter(x=>x.method==='historyCorrection').length,1);assert.equal(h.nativeCloses,1);
});

test('failed accepted preference keeps close open until acknowledged', async () => {
 const h=setup();let c=h.render();const gate=h.pause('savePreference');h.fail('savePreference',new Error('write failed'));const writing=c.run('setLanguage','pt');await gate.started;
 c.setClosing(true);c=h.render();await flush();assert.equal(h.nativeCloses,0);gate.release();await writing;await flush();c=h.render();
 assert.equal(h.nativeCloses,0);assert.equal(c.closing,false);assert.match(c.error,/write failed/);
 c=h.render();await flush();assert.equal(h.nativeCloses,0);c.setClosing(true);c=h.render();await flush();assert.equal(h.nativeCloses,1);
});

test('editing remains live while clean close awaits writes', async () => {
 const h=setup();let c=h.render();const gate=h.pause('savePreference');const writing=c.run('setLanguage','pt');await gate.started;
 c.setClosing(true);c=h.render();c.setPrompt('keep window open');c=h.render();gate.release();await writing;await flush();c=h.render();
 assert.equal(h.nativeCloses,0);assert.equal(c.prompt,'keep window open');assert.equal(c.closing,true);
});

for(const operation of ['save','load']) test(`Continue editing cancels close while ${operation} is pending`, async () => {
 const h=setup();let c=h.render();c.setPrompt('draft');c=h.render();c.setClosing(true);c=h.render();
 const gate=h.pause(operation);const pending=operation==='save'?c.saveAndClose():c.discardAndClose();await gate.started;
 c=h.render();c.cancelDiscard();c=h.render();assert.equal(c.closing,false);gate.release();await pending;await flush();c=h.render();
 assert.equal(h.nativeCloses,0);assert.equal(c.closing,false);
});


test('cancelled close cannot acknowledge a failed write for a newer close', async () => {
 const h=setup();let c=h.render();const gate=h.pause('savePreference');h.fail('savePreference',new Error('failed write'));
 const writing=c.run('setLanguage','pt');await gate.started;c.setClosing(true);c=h.render();c.cancelDiscard();c.setClosing(true);c=h.render();
 gate.release();await writing;await flush();c=h.render();assert.equal(h.nativeCloses,0);assert.equal(c.closing,false);assert.match(c.error,/failed write/);
});

test('Continue editing cancels a clean close waiting for a queued preference', async () => {
 const h=setup();let c=h.render();const gate=h.pause('savePreference');const writing=c.run('setLanguage','pt');await gate.started;
 c.setClosing(true);c=h.render();c.cancelDiscard();gate.release();await writing;await flush();c=h.render();
 assert.equal(h.nativeCloses,0);assert.equal(c.closing,false);assert.equal(h.persisted.language,'pt');
});

test('close includes writes accepted while its first batch drains', async () => {
 const h=setup();let c=h.render();const firstGate=h.pause('savePreference');const first=c.run('setLanguage','pt');await firstGate.started;
 c.setClosing(true);c=h.render();const secondGate=h.pause('savePreference');const second=c.run('setLanguage','en');firstGate.release();await secondGate.started;await first;await flush();
 assert.equal(h.nativeCloses,0);secondGate.release();await second;await flush();assert.equal(h.nativeCloses,1);assert.equal(h.persisted.language,'en');
});

test('a newer flag revision survives an earlier autosave completion', async () => {
 const h=setup();let c=h.render();await c.navigate('snippets');c=h.render();c.setSnippets([{...c.state.snippets[0],replacement:'keep draft'}]);c=h.render();
 const firstGate=h.pause('saveLibraryPreference');const first=c.setLibraryPreference('snippets',0,'enabled',false);await firstGate.started;
 const secondGate=h.pause('saveLibraryPreference');const second=c.setLibraryPreference('snippets',0,'enabled',true);firstGate.release();await secondGate.started;await first;c=h.render();
 assert.equal(c.snippets[0].enabled,true);assert.equal(c.snippets[0].replacement,'keep draft');secondGate.release();await second;c=h.render();await c.save();
 assert.equal(h.persisted.snippets[0].enabled,true);assert.equal(h.persisted.snippets[0].replacement,'keep draft');
});


for(const library of ['dictionary','snippets']) test(`failed new ${library} flag autosave remains retryable by explicit Save`, async () => {
 const h=setup();let c=h.render();await c.navigate(library);c=h.render();
 if(library==='dictionary')c.setDictionary([...c.state.dictionaryEntries,{term:'new',pronunciation:'',aliases:[],enabled:true}]);
 else c.setSnippets([...c.state.snippets,{trigger:'new',replacement:'text',enabled:true,case_sensitive:false}]);
 c=h.render();const gate=h.pause('save');const saving=c.save();await gate.started;
 const field=library==='dictionary'?'enabled':'case_sensitive';const desired=library==='snippets';
 const flag=c.setLibraryPreference(library,1,field,desired);h.fail('saveLibraryPreference',new Error('flag write failed'));gate.release();await Promise.all([saving,flag]);c=h.render();
 assert.equal((library==='dictionary'?c.dictionary:c.snippets)[1][field],desired);assert.match(c.error,/flag write failed/);
 await c.save();c=h.render();assert.equal((library==='dictionary'?h.persisted.dictionaryEntries:h.persisted.snippets)[1][field],desired);assert.equal(c.error,'');
});


for(const library of ['dictionary','snippets']) test(`${library} incoming sync retains remote additions and untouched fields before Save`, async () => {
 const h=setup();let c=h.render();await c.navigate(library);c=h.render();
 const key=library==='dictionary'?'dictionaryEntries':'snippets';const textField=library==='dictionary'?'term':'replacement';const untouched=library==='dictionary'?'pronunciation':'case_sensitive';const remoteValue=library==='dictionary'?'remote updated field':true;
 const original=clone(c.state[key][0]);const incoming={...original,[untouched]:remoteValue,enabled:false};
 const remote=library==='dictionary'?{term:'remote addition',pronunciation:'',aliases:[],enabled:true}:{trigger:'remote addition',replacement:'remote text',enabled:true,case_sensitive:false};
 if(library==='dictionary')c.setDictionary([{...original,[textField]:'local draft'}]);else c.setSnippets([{...original,[textField]:'local draft'}]);c=h.render();
 const gate=h.pause('saveLibraryPreference');const flag=c.setLibraryPreference(library,0,'enabled',false);await gate.started;
 h.syncAfterPreference(library,[incoming,remote]);gate.release();await flag;c=h.render();
 assert.equal(c.state[key].length,2,'incoming snapshot was accepted');
 await c.save();c=h.render();assert.equal(c.error,'');
 assert.equal(h.persisted[key].length,2,'replacement must include remote addition');
 assert.equal(h.persisted[key][0][textField],'local draft');assert.equal(h.persisted[key][0][untouched],remoteValue);assert.equal(h.persisted[key][0].enabled,false);
 assert.equal(h.persisted[key][1][library==='dictionary'?'term':'trigger'],'remote addition');
});

for(const library of ['dictionary','snippets']) test(`${library} sync preserves local new and deleted rows across successive snapshots`, async () => {
 const h=setup();let c=h.render();const key=library==='dictionary'?'dictionaryEntries':'snippets';
 const row=name=>library==='dictionary'?{term:name,pronunciation:'',aliases:[],enabled:true}:{trigger:name,replacement:name,enabled:true,case_sensitive:false};
 h.replaceLibrary(library,[c.state[key][0],row('delete locally'),row('delete remotely')]);await c.run('snapshot');await c.navigate(library);c=h.render();
 const first=clone(c.state[key][0]);
 if(library==='dictionary')c.setDictionary([{...first,term:'local edit'},c.state[key][2],row('local new')]);
 else c.setSnippets([{...first,replacement:'local edit'},c.state[key][2],row('local new')]);
 c=h.render();
 const remoteFirst={...first,...(library==='dictionary'?{pronunciation:'remote one'}:{case_sensitive:true})};
 h.replaceLibrary(library,[remoteFirst,row('delete locally'),row('remote new')]);await c.run('snapshot');c=h.render();
 const remoteSecond={...remoteFirst,...(library==='dictionary'?{pronunciation:'remote two'}:{case_sensitive:false})};
 h.replaceLibrary(library,[remoteSecond,row('delete locally'),row('remote new'),row('remote later')]);await c.run('snapshot');c=h.render();await c.save();c=h.render();
 const rows=h.persisted[key];const names=rows.map(x=>x[library==='dictionary'?'term':'trigger']);
 assert.equal(c.error,'');assert.ok(!names.includes('delete locally'));assert.ok(!names.includes('delete remotely'));assert.ok(names.includes('local new'));assert.ok(names.includes('remote new'));assert.ok(names.includes('remote later'));
 assert.equal(rows[0][library==='dictionary'?'term':'replacement'],'local edit');assert.equal(rows[0][library==='dictionary'?'pronunciation':'case_sensitive'],library==='dictionary'?'remote two':false);
});

for(const library of ['dictionary','snippets']) test(`${library} stale-account draft does not import or replace another context`, async () => {
 const h=setup();let c=h.render();await c.navigate(library);c=h.render();const key=library==='dictionary'?'dictionaryEntries':'snippets';
 if(library==='dictionary')c.setDictionary([{...c.state[key][0],term:'private guest draft'}]);else c.setSnippets([{...c.state[key][0],replacement:'private guest draft'}]);c=h.render();
 h.changeContext('other-account');const remote=library==='dictionary'?{term:'other account',pronunciation:'',aliases:[],enabled:true}:{trigger:'other account',replacement:'other text',enabled:true,case_sensitive:false};
 h.replaceLibrary(library,[remote]);await c.run('snapshot');c=h.render();assert.equal((library==='dictionary'?c.dictionary:c.snippets).length,1);
 assert.equal((library==='dictionary'?c.dictionary:c.snippets)[0][library==='dictionary'?'term':'replacement'],'private guest draft');assert.equal(await c.save(),false);assert.equal(h.persisted[key][0][library==='dictionary'?'term':'trigger'],'other account');
});

test('provider selection guards old-provider key and endpoint input events and validation', async () => {
 const h=setup();let c=h.render();const gate=h.pause('selectProvider');const selecting=c.selectProvider('groq');await gate.started;
 c.setApiKey('old-provider-key');c.setEndpoint('https://old-provider.test/v1');await c.validateProvider();
 c=h.render();assert.equal(c.selectingProvider,true);assert.equal(c.apiKey,'');assert.equal(c.endpoint,'');
 gate.release();await selecting;c=h.render();await c.validateProvider();c=h.render();assert.equal(c.selectingProvider,false);assert.equal(c.state.selectedProviderId,'groq');
 assert.equal(h.records.some(x=>x.method==='setProviderApiKey'||x.method==='setProviderBaseUrl'),false);
});

for(const method of ['selectLocalProfile','selectLocalDevice']) test(`local model removal rejects identity captured before queued ${method}`, async () => {
 const h=setup();let c=h.render();c.setConfirmAction('removeLocalAsr');c=h.render();const gate=h.pause(method);const selecting=c.run(method,1);await gate.started;
 const removing=c.confirmMutation();gate.release();await Promise.all([selecting,removing]);c=h.render();
 assert.equal(h.records.some(x=>x.method==='removeLocalAsr'),false);assert.ok(c.error);assert.equal(c.confirmAction,'removeLocalAsr');
});

for(const library of ['dictionary','snippets']) test(`${library} Save retains backend imports before React accepts their snapshot`, async () => {
 const h=setup();let c=h.render();await c.navigate(library);c=h.render();const key=library==='dictionary'?'dictionaryEntries':'snippets';
 const original=clone(c.state[key][0]);
 if(library==='dictionary')c.setDictionary([{...original,term:'local edit'}]);else c.setSnippets([{...original,replacement:'local edit'}]);c=h.render();
 const imported=library==='dictionary'?{term:'unpolled remote',pronunciation:'',aliases:[],enabled:true}:{trigger:'unpolled remote',replacement:'remote text',enabled:true,case_sensitive:false};
 h.replaceLibrary(library,[original,imported]);assert.equal(c.state[key].length,1,'React has not accepted the import');
 await c.save();c=h.render();assert.equal(c.error,'');
 const staged=h.records.find(x=>x.method===(library==='dictionary'?'setDictionaryEntries':'setSnippets'));
 assert.equal(staged.args[0].length,2,'first replacement must already contain the unpolled import');assert.equal(h.persisted[key].length,2);
 assert.equal(h.persisted[key][0][library==='dictionary'?'term':'replacement'],'local edit');
});


for(const library of ['dictionary','snippets']) test(`${library} snapshot mismatch rejects replacement and preserves drafts for explicit retry`, async () => {
 const h=setup();let c=h.render();await c.navigate(library);c=h.render();const key=library==='dictionary'?'dictionaryEntries':'snippets';const original=clone(c.state[key][0]);
 if(library==='dictionary')c.setDictionary([{...original,term:'retry local edit'}]);else c.setSnippets([{...original,replacement:'retry local edit'}]);c=h.render();
 const setter=library==='dictionary'?'setDictionaryEntries':'setSnippets';const gate=h.pause(setter);const saving=c.save();await gate.started;
 const remote=library==='dictionary'?{term:'late remote',pronunciation:'',aliases:[],enabled:true}:{trigger:'late remote',replacement:'remote',enabled:true,case_sensitive:false};
 h.replaceLibrary(library,[original,remote]);gate.release();assert.equal(await saving,false);c=h.render();
 assert.equal(h.persisted[key].length,2);assert.equal((library==='dictionary'?c.dictionary:c.snippets)[0][library==='dictionary'?'term':'replacement'],'retry local edit');assert.ok(c.error);
 assert.equal(await c.save(),true);c=h.render();assert.equal(c.error,'');assert.equal(h.persisted[key].length,2);assert.equal(h.persisted[key][0][library==='dictionary'?'term':'replacement'],'retry local edit');
});

for(const library of ['dictionary','snippets']) test(`${library} import reconciliation retains post-click edits and deletions through Save`, async () => {
 const h=setup();let c=h.render();await c.navigate(library);c=h.render();const key=library==='dictionary'?'dictionaryEntries':'snippets';const textField=library==='dictionary'?'term':'replacement';
 const original=clone(c.state[key][0]);const row=name=>library==='dictionary'?{term:name,pronunciation:'',aliases:[],enabled:true}:{trigger:name,replacement:name,enabled:true,case_sensitive:false};
 const set=entries=>library==='dictionary'?c.setDictionary(entries):c.setSnippets(entries);
 set([{...original,[textField]:'captured edit'},row('new before Save')]);c=h.render();h.replaceLibrary(library,[original,row('remote import')]);
 const gate=h.pause('save');const saving=c.save();await gate.started;c=h.render();const draft=library==='dictionary'?c.dictionary:c.snippets;
 set(draft.map((entry,i)=>i===0?{...entry,[textField]:'post-click edit'}:entry));c=h.render();set([(library==='dictionary'?c.dictionary:c.snippets)[0]]);
 gate.release();assert.equal(await saving,true);c=h.render();const live=library==='dictionary'?c.dictionary:c.snippets;
 assert.equal(live[0][textField],'post-click edit');assert.equal(live.length,2);assert.equal(live[1][library==='dictionary'?'term':'trigger'],'remote import');
 assert.equal(await c.save(),true);c=h.render();assert.equal(h.persisted[key].length,2);assert.equal(h.persisted[key][0][textField],'post-click edit');assert.equal(c.error,'');
});


test('local removal confirmation captures the visible product even before a new render', async () => {
 const h=setup();let c=h.render();const visible=c.state;await c.run('selectLocalProfile',1);
 c.setConfirmAction('removeLocalAsr',undefined,visible);c=h.render();await c.confirmMutation();c=h.render();assert.ok(c.error);assert.equal(h.records.some(x=>x.method==='removeLocalAsr'),false);
});

test('local removal proceeds when the confirmed product is unchanged', async () => {
 const h=setup();let c=h.render();c.setConfirmAction('removeLocalAsr',undefined,c.state);c=h.render();await c.confirmMutation();c=h.render();
 assert.equal(c.error,'');assert.equal(c.confirmAction,null);assert.equal(h.records.filter(x=>x.method==='removeLocalAsr').length,1);
});

for(const library of ['dictionary','snippets']) for(const change of ['delete','reorder']) test(`${library} Save binds queued flags by submitted identity after remote ${change}`, async () => {
 const h=setup();let c=h.render();const key=library==='dictionary'?'dictionaryEntries':'snippets';const name=library==='dictionary'?'term':'trigger';const payload=library==='dictionary'?'pronunciation':'replacement';
 const a=clone(c.state[key][0]);const b=library==='dictionary'?{term:'survivor',pronunciation:'',aliases:[],enabled:true}:{trigger:'survivor',replacement:'saved B',enabled:true,case_sensitive:false};
 h.replaceLibrary(library,[a,b]);await c.run('snapshot');await c.navigate(library);c=h.render();
 const set=entries=>library==='dictionary'?c.setDictionary(entries):c.setSnippets(entries);
 set([{...c.state[key][0],...(change==='reorder'?{[name]:'  cafe\u0301  '}:{} )},{...c.state[key][1],[payload]:'captured B edit'}]);c=h.render();
 const gate=h.pause('save');const saving=c.save();await gate.started;
 const flag=c.setLibraryPreference(library,0,'enabled',false);const caseFlag=library==='snippets'?c.setLibraryPreference(library,0,'case_sensitive',true):Promise.resolve();c=h.render();
 if(change==='reorder')set((library==='dictionary'?c.dictionary:c.snippets).map((entry,i)=>i===0?{...entry,[name]:'post-click A edit'}:entry));
 const setter=library==='dictionary'?'setDictionaryEntries':'setSnippets';const submitted=clone(h.records.findLast(x=>x.method===setter).args[0]);
 const normalized=submitted.map(entry=>Object.fromEntries(Object.entries(entry).map(([field,value])=>[field,typeof value==='string'?value.normalize('NFC'):value])));
 h.replaceLibrary(library,change==='delete'?[normalized[1]]:[normalized[1],normalized[0]]);gate.release();await Promise.all([saving,flag,caseFlag]);c=h.render();
 const saved=h.persisted[key];const survivor=saved.find(entry=>entry[name]==='survivor');assert.equal(c.error,'');assert.equal(survivor.enabled,true,'a queued flag for A must never change B');
 if(library==='snippets')assert.equal(survivor.case_sensitive,false);
 if(change==='delete'){
  assert.equal(saved.length,1);assert.equal(h.records.some(x=>x.method==='saveLibraryPreference'),false,'missing row token must be invalidated');
 }else{
  const confirmed=saved.find(entry=>entry[name]==='café');assert.equal(confirmed.enabled,false);if(library==='snippets')assert.equal(confirmed.case_sensitive,true);
  assert.equal((library==='dictionary'?c.dictionary:c.snippets)[0][name],'post-click A edit');assert.equal(await c.save(),true);c=h.render();
  const later=h.persisted[key].find(entry=>entry[name]==='post-click A edit');assert.equal(later.enabled,false);if(library==='snippets')assert.equal(later.case_sensitive,true);
 }
});


test('social cancellation bypasses account busy and draft guards; other commands stay guarded', async () => {
 const h=setup();let c=h.render();h.setAccountState({busy:true,socialPending:true});await c.run('snapshot');c=h.render();
 c.setPrompt('local draft');c=h.render();
 assert.equal(await c.run('accountCommand','logout',''),false);
 const result=await c.run('accountCommand','cancel-social','');assert.ok(result);
 assert.equal(h.records.filter(x=>x.method==='accountCommand').length,1);
 assert.deepEqual(h.records.find(x=>x.method==='accountCommand').args,['cancel-social','']);
 c=h.render();assert.equal(c.prompt,'local draft');
});

test('social cancellation accepts one request while its account operation is pending', async () => {
 const h=setup();let c=h.render();h.setAccountState({busy:true,socialPending:true});await c.run('snapshot');c=h.render();
 const gate=h.pause('accountCommand');const first=c.run('accountCommand','cancel-social','');await gate.started;
 const second=c.run('accountCommand','cancel-social','');c=h.render();assert.equal(c.accountPending,true);
 gate.release();const [accepted,rejected]=await Promise.all([first,second]);c=h.render();
 assert.ok(accepted);assert.equal(rejected,false);assert.equal(c.accountPending,false);
 assert.equal(h.records.filter(x=>x.method==='accountCommand').length,1);
});


for (const action of ['save','discard']) test(`contextual ${action} waits for its requested workflow to load`, async () => {
 const h=setup();let c=h.render();c.setPrompt('dictation draft');
 await c.navigate('text');c=h.render();c.setPrompt('text draft');c=h.render();
 const gate=h.pause('selectWorkflow');const navigation=c.navigate('dictation');await gate.started;c=h.render();
 assert.equal(c.page,'dictation');assert.equal(c.routeLoading,true);
 const operation=action==='save'?c.save():c.discardAndClose();
 gate.release();await Promise.all([navigation,operation]);c=h.render();
 assert.equal(c.state.selectedScope,'transcription');assert.equal(c.prompt,'dictation draft');
 assert.equal(h.persisted.routes.refinement.prompt,'saved-refinement');
 assert.equal(h.persisted.routes.transcription.prompt,'saved-transcription');
 await c.save();c=h.render();assert.equal(h.persisted.routes.transcription.prompt,'dictation draft');
 await c.navigate('text');c=h.render();assert.equal(c.prompt,'text draft');
});

for (const [library,field,value] of [
 ['dictionary','term','changed term'], ['dictionary','pronunciation','changed sound'],
 ['dictionary','aliases',['changed alias']], ['snippets','trigger','changed trigger'],
 ['snippets','replacement','changed replacement'],
]) test(`${library} Save preserves a post-click reversion of ${field}`, async () => {
 const h=setup();let c=h.render();await c.navigate(library);c=h.render();
 const saved=structuredClone(library==='dictionary'?c.state.dictionaryEntries:c.state.snippets);
 const set=entries=>library==='dictionary'?c.setDictionary(entries):c.setSnippets(entries);
 set([{...saved[0],[field]:value}]);c=h.render();
 const gate=h.pause('save');const saving=c.save();await gate.started;
 set([{...saved[0]}]);gate.release();await saving;c=h.render();
 const live=library==='dictionary'?c.dictionary:c.snippets;
 assert.deepEqual(structuredClone(live[0][field]),saved[0][field]);assert.equal(c.pageDirty,true);
 await c.save();c=h.render();
 const persisted=library==='dictionary'?h.persisted.dictionaryEntries:h.persisted.snippets;
 assert.deepEqual(persisted[0][field],saved[0][field]);assert.equal(c.dirty,false);
});

test('save all queued after navigation preserves the requested workflow', async () => {
 const h=setup();let c=h.render();c.setPrompt('dictation draft');await c.navigate('text');c=h.render();c.setPrompt('text draft');c=h.render();
 const gate=h.pause('selectWorkflow');const navigation=c.navigate('dictation');await gate.started;c=h.render();const saving=c.save(true);
 gate.release();await Promise.all([navigation,saving]);c=h.render();
 assert.equal(c.page,'dictation');assert.equal(c.state.selectedScope,'transcription');assert.equal(c.routeLoading,false);
 assert.equal(h.persisted.routes.transcription.prompt,'dictation draft');assert.equal(h.persisted.routes.refinement.prompt,'text draft');
});
