import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { NOTE_TYPE, MAX_BYTES, validateCheckpoint, checkpointGate, sources, latestNote } from "../runtime/lib/checkpoint.mjs";
import { loadGraph, graphStatus, queryTerms, clip } from "../runtime/lib/graph.mjs";
import extension, { POLICY } from "../runtime/extension.js";

const user = (id, text) => ({ id, type: "message", message: { role: "user", content: [{ type: "text", text }] } });
const tool = (id, name, text = "OK") => ({ id, type: "message", message: { role: "toolResult", toolName: name, content: [{ type: "text", text }] } });
const base = [user("u1", "Use staging, never deploy production. Keep 3 replicas."), user("u2", "Change replicas to 2. Old 3 is superseded. Migration remains pending.")];
const checkpoint = () => ({ version: 1, goal: { text: "Prepare staging", sources: ["u1"] }, constraints: [{ text: "No production deployment", sources: ["u1"] }],
  decisions: [{ id: "d1", text: "3 replicas", status: "superseded", sources: ["u1"] }, { id: "d2", text: "2 replicas", status: "active", supersedes: "d1", sources: ["u2"] }],
  progress: [{ text: "Migration", status: "pending", sources: ["u2"] }], next: ["Test migration"], questions: [] });
const note = (id = "n1", state = checkpoint()) => ({ id, type: "custom", customType: NOTE_TYPE, data: { version: 1, text: JSON.stringify(state) } });

test("sourced checkpoint retains constraint, replacement decision, and unfinished work", () => {
  const check = validateCheckpoint(JSON.stringify(checkpoint()), base);
  assert.equal(check.ok, true); assert.equal(check.state.decisions[1].supersedes, "d1");
});
test("reject invented IDs and IDs from another branch", () => {
  const state = checkpoint(); state.goal.sources = ["made-up"];
  assert.equal(validateCheckpoint(JSON.stringify(state), base).ok, false);
  assert.equal(validateCheckpoint(JSON.stringify(checkpoint()), [base[0]]).ok, false);
});
test("reset hides old notes and old source IDs", () => {
  const entries = [...base, note(), { id: "r1", type: "reset_boundary" }, user("u3", "new task")];
  assert.equal(latestNote(entries), undefined);
  assert.equal(validateCheckpoint(JSON.stringify(checkpoint()), entries).ok, false);
});
test("reject malformed, cleared, or oversized UTF-8 notes", () => {
  for (const raw of ["", "plain summary", "null", "[]", "{}", "я".repeat(MAX_BYTES / 2 + 1)])
    assert.equal(validateCheckpoint(raw, base).ok, false);
});
test("reject malformed items and contradictory supersession pointers", () => {
  for (const change of [s => s.constraints = [null], s => s.decisions[0].status = "active", s => s.decisions[1].supersedes = "missing", s => s.progress[0].status = "probably", s => s.next = [""]]) {
    const state = checkpoint(); change(state); assert.equal(validateCheckpoint(JSON.stringify(state), base).ok, false);
  }
});
test("optional null supersedes is harmless and must not cause a model retry", () => {
  const state=checkpoint();state.decisions[0].supersedes=null;
  assert.equal(validateCheckpoint(JSON.stringify(state),base).ok,true);
});
test("absent or stale checkpoint blocks rollover", () => {
  assert.equal(checkpointGate(base).ok, false);
  assert.equal(checkpointGate([...base, note(), tool("t1", "bash")]).ok, false);
});
test("newer work is safe when retained in tail", () => {
  const entries = [...base, note(), tool("t1", "bash"), user("u3", "new question")];
  assert.equal(checkpointGate(entries, "t1").ok, true);
  assert.equal(checkpointGate(entries, "u3").ok, false);
});
test("control tool calls and commentary do not prevent their own rollover", () => {
  const control = { id: "a1", type: "message", message: { role: "assistant", content: [{ type: "text", text: "Rolling over now" }, { type: "toolCall", name: "new_context" }] } };
  assert.equal(checkpointGate([...base, note(), tool("t0", "context_notes"), control]).ok, true);
});
test("checkpoint survives multiple native boundaries and resume reconstruction", () => {
  const journal = [...base, note(), {id:"c1",type:"compaction",details:{kind:"experimental-context-rollover"}}, tool("t1", "context_notes"), note("n2"), {id:"c2",type:"compaction",details:{kind:"experimental-context-rollover"}}];
  const restored = JSON.parse(JSON.stringify(journal));
  assert.equal(checkpointGate(restored).ok, true);
  assert.equal(latestNote(restored).id, "n2");
  assert.equal(sources(restored, "3 replicas")[0].id, "u1");
  assert.equal(JSON.parse(latestNote(restored).data.text).progress[0].status, "pending");
});
test("source retrieval is bounded and includes real camelCase toolResult", () => {
  const entries = [...base, ...Array.from({length:25}, (_, i) => tool(`t${i}`, "bash", "x".repeat(1000)))];
  const found = sources(entries); assert.equal(found.length, 12); assert.equal(found[0].preview.length, 240); assert.equal(found[0].role, "toolResult");
});

function mock() {
  const hooks = {}, tools = {}, commands = {}, messages = [], notifications = [];
  let active = ["context_notes","new_context","read","grep"];
  const schema = new Proxy(() => schema, {get:() => schema,apply:() => schema});
  const pi = { zod:schema, setLabel(){}, on:(name, fn) => {hooks[name]=fn;}, getActiveTools:() => active, setActiveTools:async names=>{active=names;},
    registerTool:t => tools[t.name]=t, registerCommand:(name,c) => commands[name]=c, sendMessage:(...x) => messages.push(x), sendUserMessage:(...x) => messages.push(x), exec:async()=>({code:0,stdout:"bounded answer",stderr:""}) };
  let branch = base;
  const ctx = {cwd:os.tmpdir(),getContextUsage:()=>({tokens:100,contextWindow:200000}),sessionManager:{getBranch:()=>branch,getSessionId:()=>"test"},hasUI:true,ui:{notify:(...x)=>notifications.push(x)}};
  extension(pi);
  return {pi,hooks,tools,commands,ctx,messages,notifications,setBranch:b=>branch=b};
}
test("policy adds one stable block without replacing host instructions", async () => {
  const m=mock(); const r=await m.hooks.before_agent_start({reason:"prompt",systemPrompt:["existing"]});
  assert.deepEqual(r.systemPrompt,["existing",POLICY]); assert.equal(await m.hooks.before_agent_start({reason:"revive"}),undefined);
});
test("missing checkpoint never blocks native summaries or schedules repair loops", async () => {
  const m=mock(), before=JSON.stringify(base); const event={branchEntries:base,preparation:{firstKeptEntryId:"u2"}};
  await m.hooks.before_agent_start({reason:"prompt",systemPrompt:[]});
  for(let i=0;i<10;i++)assert.equal(await m.hooks.session_before_compact(event,m.ctx),undefined);
  assert.equal(m.messages.length,0);assert.equal(m.hooks.session_stop,undefined);
  assert.equal(JSON.stringify(base),before);
});
test("native summaries run while invalid writes remain rejected", async () => {
  const m=mock(); const entries=[...base,note()];m.setBranch(entries);
  await m.hooks.before_agent_start({reason:"prompt",systemPrompt:[]});
  assert.equal(await m.hooks.session_before_compact({branchEntries:entries,preparation:{}},m.ctx),undefined);
  assert.equal(m.hooks.tool_call({toolName:"context_notes",input:{text:""}},m.ctx).block,true);
  assert.equal(m.hooks.tool_call({toolName:"context_notes",input:{text:JSON.stringify(checkpoint())}},m.ctx),undefined);
});
test("disabled native notes leave ordinary tools and compaction alone", async () => {
  const m=mock();m.pi.getActiveTools=()=>["read","grep"];
  assert.equal(await m.hooks.session_before_compact({branchEntries:base,preparation:{}},m.ctx),undefined);
  assert.equal(m.hooks.tool_call({toolName:"write",input:{}},m.ctx),undefined);
});
test("graph vocabulary, freshness warning and output budget", async t => {
  const root=await fs.mkdtemp(path.join(os.tmpdir(),"omp-context-unit-"));t.after(()=>fs.rm(root,{recursive:true,force:true}));
  await fs.mkdir(path.join(root,"graphify-out"));
  const file=path.join(root,"graphify-out","graph.json");
  await fs.writeFile(file,JSON.stringify({nodes:[{id:"auth",label:"AuthHandler",source_file:"auth.ts"},{id:"ru",label:"Память проекта",source_file:"missing.md"}],links:[]}));
  const old=new Date(Date.now()-10000);await fs.utimes(file,old,old);await fs.writeFile(path.join(root,"auth.ts"),"// newer");
  const graph=await loadGraph(root);assert.ok(graph.vocabulary.includes("auth"));assert.ok(graph.vocabulary.includes("память"));
  assert.deepEqual(queryTerms(["auth"],graph),["auth"]);assert.throws(()=>queryTerms(["invented"],graph));
  const status=await graphStatus(graph);assert.equal(status.newerSources,1);assert.equal(status.missingSources,1);
  assert.ok(clip("x".repeat(9000)).length<8100);
  const m=mock();const output=await m.tools.project_graph.execute("id",{action:"query",project:root,terms:["auth"]},undefined,undefined,m.ctx);
  assert.equal(JSON.parse(output.content[0].text).answer,"bounded answer");
});
