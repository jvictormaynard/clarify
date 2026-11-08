import assert from 'node:assert/strict';
import { vi } from 'vitest';
import { invoke as tauriInvoke } from '@tauri-apps/api/core';
import { getCurrentWindow } from '@tauri-apps/api/window';
import { pollSettings } from '../../src/settings/bridge';
import { mountHook } from './react-fixture';

const clone=x=>structuredClone(x);
export async function setup() {
  vi.useFakeTimers();
  const routes=Object.fromEntries(['transcription','refinement','rewrite','translation','local_asr_refinement'].map(scope=>[scope,{prompt:`saved-${scope}`,model:'model',endpoint:'',enabled:true}]));
  let persisted={routes:clone(routes),historyRetentionDays:null,recordingControls:{max_duration_seconds:null,warning_seconds:5,vad:{enabled:false,level_threshold:0.05,minimum_speech_seconds:0.1,silence_duration_seconds:0.5}},snippets:[{trigger:'sig',replacement:'saved text',enabled:true,case_sensitive:false}],dictionaryEntries:[{term:'original',pronunciation:'',aliases:[],enabled:true}]};
  let staged=clone(persisted);
  let selectedScope='transcription', microphoneTestBusy=false, selectedProviderId='cloud', snippetContext='guest',localProfileIndex=0,localDeviceIndex=0;
  const keys={cloud:true,groq:true};
  let accountState={busy:false,signedIn:false,socialPending:false};
  const snapshot=()=>({...clone(staged),routePrompt:staged.routes[selectedScope].prompt,routeModelId:staged.routes[selectedScope].model,routeCustomEndpoint:staged.routes[selectedScope].endpoint,routeEnabled:staged.routes[selectedScope].enabled,selectedScope,microphoneTestBusy,providerBaseUrl:'',providerDirty:false,dirty:false,accountState:clone(accountState),snippetContext,uiLanguage:'pt',selectedProviderId,localProfileIndex,localDeviceIndex,providerHasApiKey:keys[selectedProviderId],providers:[{id:'cloud'}]});
  const records=[];
  let nativeCloses=0, closeListener;
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
  vi.mocked(tauriInvoke).mockImplementation(invoke);
  vi.mocked(getCurrentWindow).mockReturnValue({
    close:async()=>{nativeCloses++;},
    onCloseRequested:async fn=>{closeListener=fn;return ()=>{closeListener=undefined;};},
  });
  const { useSettings } = await import('../../src/settings/use-settings');
  const hook = await mountHook(useSettings);
  await vi.waitFor(() => assert.ok(hook.render().state, 'initial Settings snapshot'));
  return {render:hook.render, records, get persisted(){return persisted;}, get keys(){return keys;}, get nativeCloses(){return nativeCloses;},
    setAccountState(value){accountState={...accountState,...value};},
    replaceLibrary(library,entries){const key=library==='dictionary'?'dictionaryEntries':'snippets';persisted[key]=clone(entries);staged[key]=clone(entries);},
    syncAfterPreference(library,entries){afterPreference=()=>{const key=library==='dictionary'?'dictionaryEntries':'snippets';persisted[key]=clone(entries);staged[key]=clone(entries);};},
    close(){let prevented=false;closeListener({preventDefault(){prevented=true;}});return prevented;}, changeContext(value){snippetContext=value;}, poll(){return pollSettings();},
    pause(method){let release,started;const wait=new Promise(r=>release=r);const beginning=new Promise(r=>started=r);gate={method,wait,started};return {release,started:beginning};},
    fail(method,error){failure={method,error};},
  };
}