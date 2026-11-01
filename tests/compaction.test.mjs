import test from "node:test";
import assert from "node:assert/strict";
import {installCompaction} from "../runtime/lib/compaction.mjs";

function mock(active=["read","grep","context_notes","new_context","bash"]) {
  const hooks={},calls=[];
  const pi={getActiveTools:()=>active,setActiveTools:async names=>{active=names;calls.push(names);},on:(name,fn)=>hooks[name]=fn};
  const ensure=installCompaction(pi);
  return {pi,hooks,calls,ensure,set:names=>{active=names;}};
}
test("native summary mode excludes only rollover and keeps native notes, history tools and work tools",async()=>{
  const m=mock();await m.hooks.session_start();
  assert.deepEqual(m.pi.getActiveTools(),["read","grep","context_notes","bash"]);
  await m.ensure();await m.hooks.session_branch();await m.hooks.session_tree();
  assert.equal(m.calls.length,1);
});
test("restricted tools are never expanded",async()=>{
  const m=mock(["read"]);await m.ensure();assert.deepEqual(m.pi.getActiveTools(),["read"]);assert.equal(m.calls.length,0);
});
test("a tool-surface change cannot restore unsafe notebook-only rollover",async()=>{
  const m=mock();await m.ensure();m.set(["read","grep","context_notes","new_context"]);
  const ctx={hasUI:false};
  assert.deepEqual(await m.hooks.session_before_compact({},ctx),{cancel:true});
  assert.equal(await m.hooks.session_before_compact({},ctx),undefined);
  assert.equal(m.hooks.session_stop,undefined);
});
test("summary guidance preserves pending work without replacing the native summarizer",()=>{
  const m=mock(),r=m.hooks["session.compacting"]();
  assert.equal(typeof r.context[0],"string");assert.equal(r.prompt,undefined);assert.equal(r.compaction,undefined);
});
