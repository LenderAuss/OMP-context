import test from "node:test";
import assert from "node:assert/strict";
import {sourceCatalogue,compileCheckpoint,installNotebook} from "../runtime/lib/notebook.mjs";

const entries=[{id:"user-a",type:"message",message:{role:"user",content:"Use staging only"}},{id:"user-b",type:"message",message:{role:"user",content:"Migration is pending"}}];
const catalog=sourceCatalogue(entries,"","session-one");
const input=()=>({catalogue:catalog.id,state:{goal:{text:"Prepare staging",sources:["S1"]},decisions:[{text:"Use staging",sources:["S1"]}],progress:[{text:"Migration",sources:["S2"],status:"pending"}]}});

test("structured notes expand real source refs and generate boilerplate without mutating input",()=>{
  const original=input(),before=JSON.stringify(original);
  const state=JSON.parse(compileCheckpoint(original,entries,catalog,"session-one"));
  assert.deepEqual(state.goal.sources,["user-a"]);assert.deepEqual(state.progress[0].sources,["user-b"]);
  assert.equal(state.decisions[0].id,"d1");assert.equal(state.decisions[0].status,"active");
  assert.equal(state.version,1);assert.deepEqual(state.constraints,[]);assert.equal(JSON.stringify(original),before);
});
test("stale, invented and other-session refs cannot silently bind to a different source",()=>{
  for(const mutate of [i=>i.catalogue="old",i=>i.state.goal.sources=["S99"],i=>i.state.goal.sources=["invented-id"]]) {
    const value=input();mutate(value);assert.throws(()=>compileCheckpoint(value,entries,catalog,"session-one"));
  }
  assert.throws(()=>compileCheckpoint(input(),entries,catalog,"another-session"));
  assert.throws(()=>compileCheckpoint(input(),[entries[1]],catalog,"session-one"));
});
test("legacy serialized notes remain supported and ambiguous input is rejected",()=>{
  assert.equal(compileCheckpoint({text:"existing"},entries,null,"s"),"existing");
  assert.equal(compileCheckpoint({},entries,null,"s"),undefined);
  assert.throws(()=>compileCheckpoint({...input(),text:"also supplied"},entries,catalog,"session-one"));
});
test("in_progress is saved as unfinished and catalogue IDs cannot masquerade as citations",()=>{
  const value=input();value.state.progress[0].status="in_progress";
  assert.equal(JSON.parse(compileCheckpoint(value,entries,catalog,"session-one")).progress[0].status,"pending");
  assert.equal(value.state.progress[0].status,"in_progress");
  value.state.goal.sources=[catalog.id];
  assert.throws(()=>compileCheckpoint(value,entries,catalog,"session-one"),/not a source/);
});
test("native notebook is the only writer and disabled notes mode is not replaced",async()=>{
  const hooks={},tools={};let nativeCalls=0;
  const schema=new Proxy(()=>schema,{get:()=>schema,apply:()=>schema});
  let enabled=false;
  const pi={zod:schema,on:(name,fn)=>(hooks[name]??=[]).push(fn),registerTool:t=>tools[t.name]=t,getActiveTools:()=>enabled?["context_notes"]:[]};
  const catalogFor=installNotebook(pi);
  for(const fn of hooks.session_start)fn();assert.equal(tools.context_notes,undefined);
  enabled=true;for(const fn of hooks.session_start)fn();
  const ctx={sessionManager:{getBranch:()=>entries,getSessionId:()=>"session-one"},invokeTool:async(params)=>{nativeCalls++;return {content:[{type:"text",text:params.text??"native read"}],details:{native:true}};}};
  const offered=catalogFor(ctx,"");const value=input();value.catalogue=offered.catalogue;
  const output=await tools.context_notes.execute("id",value,undefined,undefined,ctx);
  assert.equal(output.details.native,true);assert.equal(nativeCalls,1);
  await tools.context_notes.execute("id",{},undefined,undefined,ctx);assert.equal(nativeCalls,2);
  await assert.rejects(()=>tools.context_notes.execute("id",{text:"invalid"},undefined,undefined,ctx));assert.equal(nativeCalls,2);
});
