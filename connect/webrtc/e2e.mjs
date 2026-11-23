// Run from repo root: node connect/webrtc/e2e.mjs /tmp/task-owned-evidence
import {chromium} from '../../desktop/node_modules/playwright-core/index.mjs';
import {spawn, execFileSync} from 'node:child_process';
import {randomBytes} from 'node:crypto';
import {mkdir, readFile, writeFile, rm} from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import readline from 'node:readline';
const output = path.resolve(process.argv[2]);
if (!output.startsWith('/tmp/')) throw Error('Evidence must be in /tmp');
await mkdir(output, {recursive: true});
const token = randomBytes(32).toString('hex'), secret = randomBytes(32).toString('hex');
const container = `clarify-webrtc-${randomBytes(6).toString('hex')}`;
const turnPort = 54879;
let server, browser, context, electron;
const useElectron=process.argv[3]==='--electron';
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
try {
  // Authenticated, bounded, loopback-only TURN. No shared firewall/proxy edits.
  execFileSync('docker', ['run', '-d', '--name', container, '--network', 'host', '--memory', '128m', '--cpus', '0.5',
    'coturn/coturn@sha256:71c3c990283385567f11794ee692e3a47b66fd9b0bb39e42afbe776e331dd888',
    '-n', '--listening-ip=127.0.0.1', '--relay-ip=127.0.0.1', `--listening-port=${turnPort}`, '--min-port=54900', '--max-port=54930',
    '--realm=clarify-transport-test', '--use-auth-secret', `--static-auth-secret=${secret}`, '--no-tls', '--no-dtls', '--no-cli',
    '--allow-loopback-peers', '--no-multicast-peers', '--user-quota=4', '--total-quota=16', '--max-bps=1048576', '--simple-log'], {stdio:'pipe'});
  server = spawn('/tmp/clarify-audio-venv/bin/python', ['-m', 'connect.webrtc.e2e_server'], {env: {...process.env,
    CLARIFY_WEBRTC_EVIDENCE: output, CLARIFY_WEBRTC_TEST_TOKEN: token, CLARIFY_WEBRTC_TURN_SECRET: secret, CLARIFY_WEBRTC_TURN_PORT: String(turnPort)}, stdio: ['pipe','pipe','pipe']});
  readline.createInterface({input:server.stdout}).on('line', line => { if (electron) electron.stdin.write(line+'\n'); });
  let logs = ''; server.stderr.on('data', b => { logs += b; });
  let ready;
  for (let i=0; i<100; i++) { try { ready=JSON.parse(await readFile(path.join(output,'ready.json'))); break; } catch {} await pause(100); }
  if (!ready) throw Error(logs || 'server_start_timeout');
  const base = `http://127.0.0.1:${ready.port}`;
  const post = async (route, body) => { const r = await fetch(base + route, {method:'POST', headers: {Authorization:'Bearer '+token,'Content-Type':'application/json'}, body:JSON.stringify(body)}); assert.equal(r.status,200); return r.json(); };
  const fixture = await post('/fixture', {});
  browser = await chromium.launch({executablePath:'/usr/bin/google-chrome', headless:true, args:['--no-sandbox','--disable-dev-shm-usage']});
  context = await browser.newContext({viewport:{width:1100,height:780}, recordVideo:{dir:output}});
  const page = await context.newPage();
  await page.exposeFunction('computerDispatch', value => post('/dispatch', value));
  // Trusted test pipe holds bridge/account credentials outside the page.
  await page.exposeFunction('signalCall', async value => {
    const r = await fetch(`http://127.0.0.1:${ready.signalPort}/signal`, {method:'POST',headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},body:JSON.stringify(value)});
    if (!r.ok) throw Error('signaling_rejected: '+value.action); return r.json();
  });
  await page.exposeFunction('startElectron', async privateJwk => {
    const config=path.join(output,'electron-config.json');
    await writeFile(config,JSON.stringify({token,privateJwk,host:fixture.host,signalURL:`http://127.0.0.1:${ready.signalPort}/signal`,dispatchURL:base+'/dispatch'}),{mode:0o600});
    electron=spawn('xvfb-run',['-a',path.resolve('desktop/node_modules/electron/dist/electron'),'--no-sandbox',path.resolve('connect/webrtc/e2e-electron.cjs'),config],{detached:true,stdio:['pipe','pipe','pipe']});
    readline.createInterface({input:electron.stdout}).on('line', line => { if(line.startsWith('{')) server.stdin.write(line+'\n'); });
    let errors='';electron.stderr.on('data',b=>{errors+=b;});
    await new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>reject(Error('electron_start_timeout: '+errors)),20000);
      electron.stdout.on('data',b=>{if(b.toString().includes('READY')){clearTimeout(timer);resolve();}});
      electron.once('exit',()=>{clearTimeout(timer);reject(Error('electron_exited: '+errors));});
    });
    return true;
  });
  await page.exposeFunction('fixtureControl', (action, body = {}) => post('/'+action, body));
  const invalidSignal = await fetch(`http://127.0.0.1:${ready.signalPort}/signal`, {method:'POST', headers:{Authorization:'Bearer invalid'}, body:JSON.stringify({action:'create',host:fixture.host})});
  assert.equal(invalidSignal.status,403);
  await page.exposeFunction('captureLive', async live => {await writeFile(path.join(output,live.relay?'live-relay.json':'live-direct.json'),JSON.stringify(live,null,2));await page.screenshot({path:path.join(output,live.relay?'live-relay.png':'live-direct.png')});});
  await page.goto(base);
  const result = await page.evaluate(async ({fixture,useElectron}) => {
    const {clientOffer, hostAnswer} = await import('/webrtc-transport.mjs');
    const {d, ...publicKey} = fixture.privateJwk;
    const keys = {privateKey: await crypto.subtle.importKey('jwk', fixture.privateJwk, {name:'ECDSA',namedCurve:'P-256'}, true, ['sign'])};
    const signal = (action, fields={}) => window.signalCall({host:fixture.host,action,...fields});
    await signal('enroll',{public_key:publicKey});
    if(useElectron)await window.startElectron(await crypto.subtle.exportKey('jwk',keys.privateKey));
    const runs=[];
    const connectionCount=fixture.livePCM?1:5;
    for (const relay of [false,true]) for (let i=0;i<connectionCount;i++) {
      const started=performance.now();
      const {ticket}=await signal('create',{relay});
      const {iceServers}=await signal('turn',{ticket});
      const client=await clientOffer({iceServers:relay ? iceServers:[],relay});
      await signal('offer',{ticket,payload:client.offer});
      const {offer}=await signal('poll',{ticket});
      let host,answer;
      if(useElectron){
        const deadline=Date.now()+20000;
        while(Date.now()<deadline){answer=(await signal('poll',{ticket})).answer;if(answer)break;await new Promise(r=>setTimeout(r,100));}
        if(!answer)throw Error('electron_answer_timeout');
        host={pc:{close(){}}};
      }else{
        host=await hostAnswer({ticket,host:fixture.host,offer,privateKey:keys.privateKey,iceServers:relay ? iceServers:[],relay,dispatch:window.computerDispatch});
        await signal('answer',{ticket,payload:host.answer});
        answer=(await signal('poll',{ticket})).answer;
      }
      await client.accept({ticket,host:fixture.host,answer,pinnedPublicKey:publicKey});
      const setup=performance.now()-started;
      if (!relay && i === 0) {
        const wrongKeys = await crypto.subtle.generateKey({name:'ECDSA',namedCurve:'P-256'}, true, ['sign','verify']);
        const wrongPublic = await crypto.subtle.exportKey('jwk', wrongKeys.publicKey);
        const attacker = await clientOffer();
        let rejected=false;
        try { await attacker.accept({ticket,host:fixture.host,answer,pinnedPublicKey:wrongPublic}); } catch { rejected=true; }
        attacker.pc.close();
        if(!rejected)throw Error('wrong_host_key_accepted');
      }
      const rpc = body => client.rpc.request(body);
      const status={method:'GET',path:'/v1/computer/status',authorization:fixture.authorization};
      const invalid=await rpc({...status,authorization:'Bearer invalid'});
      if(invalid.status!==401) throw Error('invalid_auth_accepted');
      const rtt=[];
      for(let n=0;n<20;n++){const at=performance.now();const r=await rpc(status);if(r.status!==200)throw Error(JSON.stringify(r));rtt.push(performance.now()-at);}
      // Same operation across all connections proves persisted once-only replay.
      const text=await rpc({method:'POST',path:'/v1/computer/text',authorization:fixture.authorization,body:fixture.text});
      if(text.status!==200)throw Error(JSON.stringify(text));
      if(i===0){
        const liveOperation=(await window.fixtureControl('fixture')).operation;
        const recognition=(action,body) => rpc({recognition:action,authorization:fixture.authorization,operation_id:liveOperation,body});
        if(fixture.livePCM){
          const resourcesBefore=await window.fixtureControl('resources');
          const started=performance.now();
          const start=await recognition('start',{language:'en-US'});
          if(start.status!==200)throw Error('live_start: '+JSON.stringify(start));
          const pcm=Uint8Array.from(atob(fixture.livePCM),c=>c.charCodeAt(0));
          const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',pcm)),b=>b.toString(16).padStart(2,'0')).join('');
          let partialAt=null,partialText='',sequence=0;
          const feedStart=performance.now();
          let latestPartial='';
          for(let offset=0;offset<pcm.length;offset+=4*2560){
            const end=Math.min(offset+4*2560,pcm.length);
            const due=feedStart+end/32;
            if(performance.now()<due)await new Promise(r=>setTimeout(r,due-performance.now()));
            const frames=[];
            for(let position=offset;position<end;position+=2560) {
              frames.push({sequence:sequence++,data:btoa(String.fromCharCode(...pcm.slice(position,Math.min(position+2560,end))))});
            }
            const frame=await recognition('feed',{frames});
            if(frame.status!==200)throw Error('live_feed: '+JSON.stringify(frame));
            if(typeof frame.body.partial==='string')latestPartial=frame.body.partial;
            if(latestPartial && partialAt===null){partialAt=performance.now()-started;partialText=latestPartial;}
            document.querySelector('#result').textContent=`${relay?'TURN':'Direct'} live recognition\n${latestPartial||'Listening…'}`;
          }
          const eof=performance.now()-started;
          const final=await recognition('finish',{sha256:digest,bytes:pcm.length});
          if(final.status!==200)throw Error('live_finish: '+JSON.stringify(final));
          if(partialAt===null || partialAt>=eof)throw Error('no_partial_before_eof');
          const live={relay,partialAt,eof,finalAt:performance.now()-started,partialText,final:final.body,bytes:pcm.length,digest};
          live.resourcesBefore=resourcesBefore;
          live.resourcesAfter=await window.fixtureControl('resources');
          (window.liveRuns??=[]).push(live);
          document.querySelector('#result').textContent=JSON.stringify(window.liveRuns,null,2);
          await window.captureLive(live);
        }else if(!relay){
        if((await recognition('start',{language:'auto'})).status!==200)throw Error('start');
        if((await recognition('feed',{sequence:0,data:fixture.audio})).status!==200)throw Error('audio_feed');
        if((await recognition('finish')).status!==200)throw Error('audio_finish');
        }

      }
      if (relay && i === connectionCount-1) {
        const fresh=await window.fixtureControl('fixture');
        await window.fixtureControl('block');
        const active=rpc({method:'POST',path:'/v1/computer/text',authorization:fixture.authorization,body:fresh.text});
        for(let n=0;n<100;n++) {if((await window.fixtureControl('entered')).entered)break;await new Promise(r=>setTimeout(r,10));}
        const cancel=await rpc({method:'DELETE',path:'/v1/computer/operations/'+fresh.text.operation_id,authorization:fixture.authorization});
        if(cancel.status!==200)throw Error('active_cancel');
        await window.fixtureControl('release');
        if((await active).status!==409)throw Error('cancelled_result_published');

        const cancelled=structuredClone(fixture.text); // Cancel an already known ID: later inference must not run again.
        await rpc({method:'DELETE',path:'/v1/computer/operations/'+cancelled.operation_id,authorization:fixture.authorization});
        const after=await rpc({method:'POST',path:'/v1/computer/text',authorization:fixture.authorization,body:cancelled});
        if(after.status!==409)throw Error('cancel_failed');
        // Remaining iterations need a distinct accepted text ID, supplied below by status only.
      }
      const stats=await client.pc.getStats();let pair, candidate, transport;
      stats.forEach(v=>{if(v.type==='transport')transport=v;});
      if(transport?.selectedCandidatePairId){pair=stats.get(transport.selectedCandidatePairId);candidate=stats.get(pair.localCandidateId);}
      if(relay && candidate?.candidateType!=='relay')throw Error('not_relay: '+JSON.stringify({candidate,pair,transport}));
      let bytesSent=0,bytesReceived=0,dataBytesSent=0,dataBytesReceived=0;
      stats.forEach(value=>{
        if(value.type==='candidate-pair'){bytesSent+=value.bytesSent??0;bytesReceived+=value.bytesReceived??0;}
        if(value.type==='data-channel'){dataBytesSent+=value.bytesSent??0;dataBytesReceived+=value.bytesReceived??0;}
      });
      runs.push({relay,setup,rtt,bytesSent,bytesReceived,dataBytesSent,dataBytesReceived,candidate:candidate?.candidateType});
      if(useElectron && !relay && i===connectionCount-1) {
        const fresh=await window.fixtureControl('fixture');
        await window.fixtureControl('block');
        const active=rpc({method:'POST',path:'/v1/computer/text',authorization:fixture.authorization,body:fresh.text})
          .then(value=>({value}), error=>({error:String(error)}));
        let entered=false;
        for(let n=0;n<100;n++) { if((await window.fixtureControl('entered')).entered){entered=true;break;} await new Promise(r=>setTimeout(r,10)); }
        if(!entered)throw Error('disconnect_inference_not_entered');
        const disconnectedAt=performance.now();
        client.rpc.close();
        let cancelled=false;
        for(let n=0;n<300;n++) {
          const state=await window.fixtureControl('operation-state',{operation_id:fresh.text.operation_id});
          if(state.state==='cancelled'){cancelled=true;break;}
          await new Promise(r=>setTimeout(r,10));
        }
        await window.fixtureControl('release');
        if(!cancelled || !(await active).error)throw Error('disconnect_did_not_cancel');
        runs.at(-1).disconnectCancellationMS=performance.now()-disconnectedAt;
      }
      if(relay && i===connectionCount-1) {
        await window.fixtureControl('revoke');
        if((await rpc(status)).status!==401)throw Error('revoked_device_accepted');
      }
      client.rpc.close();client.pc.close();host.pc.close();await signal('close',{ticket});
      document.querySelector('#result').textContent=runs.map((r,n)=>`${n+1}. ${r.relay?'TURN relay':'Direct'} (${r.candidate}) | setup ${r.setup.toFixed(1)} ms | RTT median ${[...r.rtt].sort((a,b)=>a-b)[10].toFixed(1)} ms | sent ${r.bytesSent} B | received ${r.bytesReceived} B`).join('\n\n');
    }
    await signal('revoke');
    let rejected=false;try{await signal('create');}catch{rejected=true;}
    if(!rejected)throw Error('revoked_host_accepted');
    return runs;
  }, {fixture,useElectron});
  const electronResources=async()=>{
    if(!electron)return null;
    const rows=execFileSync('ps',['-eo','pid=,pgid='],{encoding:'utf8'}).trim().split('\n').map(s=>s.trim().split(/\s+/).map(Number)).filter(([,group])=>group===electron.pid);
    let ticks=0,rss=0;
    for(const [pid]of rows)try{const stat=(await readFile(`/proc/${pid}/stat`,'utf8')).slice((await readFile(`/proc/${pid}/stat`,'utf8')).lastIndexOf(')')+2).split(' ');ticks+=Number(stat[11])+Number(stat[12]);const status=await readFile(`/proc/${pid}/status`,'utf8');rss+=Number(status.match(/VmRSS:\s+(\d+)/)?.[1]??0)*1024;}catch{}
    return {ticks,rss,processes:rows.length};
  };
  const electronBefore=await electronResources();
  const cdp=await browser.newBrowserCDPSession();
  const procBefore=await cdp.send('SystemInfo.getProcessInfo');
  const serverBefore=(await readFile(`/proc/${server.pid}/stat`,'utf8')).split(' ');
  await pause(5000);
  const procAfter=await cdp.send('SystemInfo.getProcessInfo');
  const serverAfter=(await readFile(`/proc/${server.pid}/stat`,'utf8')).split(' ');
  let rss=0;
  for(const proc of procAfter.processInfo){try{const status=await readFile(`/proc/${proc.id}/status`,'utf8');rss+=Number(status.match(/VmRSS:\s+(\d+)/)?.[1]??0)*1024;}catch{}}
  const cpuSeconds=procAfter.processInfo.reduce((n,p)=>n+p.cpuTime-(procBefore.processInfo.find(b=>b.id===p.id)?.cpuTime??p.cpuTime),0);
  const electronAfter=await electronResources();
  const serverRSS=Number((await readFile(`/proc/${server.pid}/status`,'utf8')).match(/VmRSS:\s+(\d+)/)?.[1]??0)*1024;
  const resource={idleSeconds:5,activePeers:0,browserCPUPercent:100*cpuSeconds/5,browserRSSBytes:rss,bridgeCPUPercent:100*((+serverAfter[13]+ +serverAfter[14])-(+serverBefore[13]+ +serverBefore[14]))/100/5,bridgeRSSBytes:serverRSS,turn:execFileSync('docker',['stats','--no-stream','--format','{{json .}}',container],{encoding:'utf8'}).trim()};
  if(electronAfter)resource.electron={CPUPercent:100*(electronAfter.ticks-electronBefore.ticks)/Number(execFileSync('getconf',['CLK_TCK'],{encoding:'utf8'}))/5,RSSBytes:electronAfter.rss,processes:electronAfter.processes};
  await writeFile(path.join(output,'resources.json'),JSON.stringify(resource,null,2));
  await writeFile(path.join(output,'turn.log'),execFileSync('docker',['logs',container]));
  await page.screenshot({path:path.join(output,'transport.png'),fullPage:true});
  await writeFile(path.join(output,'metrics.json'),JSON.stringify(result,null,2));
  const summary=result.reduce((acc,r)=>{const key=r.relay?'relay':'direct';(acc[key]??=[]).push(r);return acc;},{});
  const percentile=(values,p)=>values.sort((a,b)=>a-b)[Math.ceil(values.length*p)-1];
  for(const [mode,runs] of Object.entries(summary)) summary[mode]={setups:runs.length,setupP50:percentile(runs.map(r=>r.setup),.5),setupP95:percentile(runs.map(r=>r.setup),.95),rttP50:percentile(runs.flatMap(r=>r.rtt),.5),rttP95:percentile(runs.flatMap(r=>r.rtt),.95),bytesSent:runs.reduce((n,r)=>n+r.bytesSent,0),bytesReceived:runs.reduce((n,r)=>n+r.bytesReceived,0)};
  await writeFile(path.join(output,'summary.json'),JSON.stringify(summary,null,2));
  console.log(JSON.stringify(summary));
} finally {
  await context?.close(); await browser?.close();
  await rm(path.join(output,'electron-config.json'),{force:true});
  if(electron){try{process.kill(-electron.pid,'SIGTERM');}catch{}}
  if(server && server.exitCode===null){server.kill('SIGTERM'); await new Promise(resolve=>{server.once('exit',resolve);setTimeout(()=>{server.kill('SIGKILL');resolve();},5000);});}
  try {execFileSync('docker',['rm','-f',container],{stdio:'pipe'});}catch{}
}
