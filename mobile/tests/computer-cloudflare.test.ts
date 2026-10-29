// @ts-nocheck -- Node VM fixture isolates the CommonJS Expo plugin.
﻿import assert from 'node:assert/strict';
import { test } from 'node:test';
import fs from 'node:fs';
import vm from 'node:vm';
const source = fs.readFileSync(new URL('../plugins/with-computer-relay.cjs',import.meta.url),'utf8');
const disabled = {schema_version:1,control_url:null,tunnel_domain:null};
const enabled = {schema_version:1,control_url:'https://clarify-connect.victormaynard.com',tunnel_domain:'victormaynard.com'};
function evaluate(cloudflare, plist={}, relayHost=null) {
  const sandbox={module:{exports:{}},URL,process:{env:{}},require(name){
    if(name==='expo/config-plugins') return {withInfoPlist(config,callback){return callback({modResults:config}).modResults}};
    if(name==='../../shared/computer_cloudflare.json') return cloudflare;
    if(name==='../../shared/computer_connect.json') return {schema_version:1,relay_host:relayHost,relay_port:443};
    throw Error('Unexpected dependency '+name);
  }};
  vm.runInNewContext(source,sandbox);
  return sandbox.module.exports(plist);
}
test('public configuration is OFF and leaves existing ATS policy unchanged',()=>{
  assert.deepEqual(disabled,{schema_version:1,control_url:null,tunnel_domain:null});
  const ats={NSAllowsLocalNetworking:true}; const plist={NSAppTransportSecurity:ats};
  assert.equal(evaluate(disabled,plist),plist);
  assert.deepEqual(plist,{NSAppTransportSecurity:ats});
});
test('enabled config writes the two fixed public keys without Cloudflare ATS exceptions',()=>{
  const ats={NSAllowsLocalNetworking:true,NSExceptionDomains:{'192.168.0.0':{fixture:true}}};
  const plist=evaluate(enabled,{NSAppTransportSecurity:ats});
  assert.equal(plist.ClarifyConnectCloudflareControlURL,enabled.control_url);
  assert.equal(plist.ClarifyConnectCloudflareDomain,enabled.tunnel_domain);
  assert.equal(plist.NSAppTransportSecurity,ats);
});
test('partial unknown and mistyped configuration fails closed',()=>{
  for (const settings of [null,{}, {...disabled,extra:true},{...disabled,schema_version:true},
    {...disabled,control_url:enabled.control_url},{...disabled,tunnel_domain:enabled.tunnel_domain},
    {...enabled,control_url:true},{...enabled,tunnel_domain:42}]) assert.throws(()=>evaluate(settings),/Cloudflare build/);
});
test('noncanonical control URLs and external origins are rejected',()=>{
  for(const control_url of ['http://clarify-connect.victormaynard.com',enabled.control_url+'/',enabled.control_url+':443',
    enabled.control_url+':444',enabled.control_url+'?x=1',enabled.control_url+'#x',enabled.control_url+'/v1',
    'https://user@clarify-connect.victormaynard.com','https://evil.example.com','https://clarify-connect.victormaynard.com.evil.com',
    'https://CLARIFY-CONNECT.victormaynard.com',enabled.control_url+'\n']) assert.throws(()=>evaluate({...enabled,control_url}),/Cloudflare build/);
});
test('invalid DNS scopes and insufficient namespace capacity are rejected',()=>{
  for(const tunnel_domain of ['*.victormaynard.com','victormaynard.com.','Victormaynard.com','localhost',
    'tunnel.local','tunnel.123','127.0.0.1','victormaynard..com','-victormaynard.com','victormaynard.com/','a'.repeat(199)])
    assert.throws(()=>evaluate({...enabled,tunnel_domain}),/Cloudflare build/);
});
test('stale native keys require a clean prebuild, including OFF transitions',()=>{
  for(const plist of [{ClarifyConnectCloudflareControlURL:'https://old.victormaynard.com'},
    {ClarifyConnectCloudflareDomain:'old.example.com'}]) assert.throws(()=>evaluate(enabled,plist),/Stale Clarify Cloudflare/);
  assert.throws(()=>evaluate(disabled,{ClarifyConnectCloudflareDomain:enabled.tunnel_domain}),/Stale Clarify Cloudflare/);
});
test('an unchanged native Cloudflare configuration can be regenerated',()=>{
  const plist={ClarifyConnectCloudflareControlURL:enabled.control_url,ClarifyConnectCloudflareDomain:enabled.tunnel_domain};
  assert.equal(evaluate(enabled,plist),plist);
});
test('existing optional raw relay still has its own scoped policy',()=>{
  const plist=evaluate(enabled,{},'relay.example.com');
  assert.equal(plist.ClarifyConnectRelayHost,'relay.example.com');
  assert.equal(plist.NSAppTransportSecurity.NSExceptionDomains['relay.example.com'].NSIncludesSubdomains,true);
  assert.equal(plist.NSAppTransportSecurity.NSExceptionDomains['victormaynard.com'],undefined);
});
