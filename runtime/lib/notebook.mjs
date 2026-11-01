import {createHash} from "node:crypto";
import {sources, validateCheckpoint} from "./checkpoint.mjs";

export function sourceCatalogue(entries, query, session) {
  const found=sources(entries,query);
  const id=createHash("sha256").update(JSON.stringify([session,found.map(x=>x.id)])).digest("hex").slice(0,12);
  return {id,session,sources:found.map((item,index)=>({...item,ref:`S${index+1}`}))};
}

export function compileCheckpoint(input, entries, catalogue, session) {
  if(input.text!==undefined&&input.state!==undefined)throw new Error("Use either state or legacy text, not both.");
  if(input.state===undefined)return input.text;
  const state=structuredClone(input.state);
  state.version=1;
  for(const key of ["constraints","decisions","progress","next","questions"])state[key]??=[];
  state.decisions.forEach((item,index)=>{item.id??=`d${index+1}`;item.status??="active";});
  // In-progress work is unfinished, never completed. Accept this common model
  // spelling while keeping the stored v1 schema and older readers compatible.
  state.progress.forEach(item=>{if(item.status==="in_progress")item.status="pending";});
  const map=new Map(catalogue?.sources.map(item=>[item.ref,item.id]));
  for(const item of [state.goal,...state.constraints,...state.decisions,...state.progress]) {
    if(!item||!Array.isArray(item.sources))throw new Error("Every claim requires text and sources from context_probe.");
    item.sources=item.sources.map(source=>{
      if(source===input.catalogue)
        throw new Error("catalogue identifies a list, not a source. Call context_probe(action=sources), put its catalogue in catalogue and refs such as S1 in sources. Never invent identifiers.");
      if(!/^S\d+$/.test(source))return source;
      if(!catalogue||catalogue.session!==session||input.catalogue!==catalogue.id||!map.has(source))
        throw new Error("Source catalogue is missing or stale. Call context_probe(action=sources) and use its catalogue and refs.");
      return map.get(source);
    });
  }
  const raw=JSON.stringify(state),check=validateCheckpoint(raw,entries);
  if(!check.ok)throw new Error(`Checkpoint not saved: ${check.errors.join(" ")}`);
  return raw;
}

export function installNotebook(pi) {
  let catalogue;
  for(const event of ["session_start","session_branch","session_tree"])
    pi.on(event,()=>{catalogue=undefined;});
  // Late registration preserves the native tool set when experimental notes are disabled.
  pi.on("session_start",()=>{
    if(!pi.getActiveTools().includes("context_notes"))return;
    const z=pi.zod;
    const claim={text:z.string().min(1).max(1800),sources:z.array(z.string().min(1)).min(1).max(8),memory_key:z.string().max(80).optional()};
    pi.registerTool({
      name:"context_notes",label:"Context notes",approval:"write",
      description:"Read native notes with no arguments. Save using state and source refs from context_probe; include its catalogue. JSON serialization, version, empty arrays and missing decision IDs are generated locally. Legacy text is supported. Source validation does not prove the claim is true.",
      parameters:z.object({catalogue:z.string().max(64).optional(),text:z.string().optional(),state:z.object({
        goal:z.object(claim),constraints:z.array(z.object(claim)).max(40).optional(),
        decisions:z.array(z.object({...claim,id:z.string().min(1).optional(),status:z.enum(["active","superseded","rejected"]).optional(),supersedes:z.string().nullable().optional()})).max(40).optional(),
        progress:z.array(z.object({...claim,status:z.enum(["done","pending","blocked","in_progress"])})).max(40).optional(),
        next:z.array(z.string().min(1)).max(20).optional(),questions:z.array(z.string().min(1)).max(20).optional()
      }).optional()}),
      async execute(_id,input,signal,onUpdate,ctx) {
        if(!ctx.invokeTool)throw new Error("Native context_notes delegation is unavailable. Enable experimental context management and restart OMP.");
        const entries=ctx.sessionManager.getBranch();
        const text=compileCheckpoint(input,entries,catalogue,ctx.sessionManager.getSessionId());
        if(text!==undefined){
          const check=validateCheckpoint(text,entries);
          if(!check.ok)throw new Error(`Checkpoint not saved: ${check.errors.join(" ")}`);
        }
        return ctx.invokeTool(text===undefined?{}:{text},{signal,onUpdate});
      }
    });
  });
  return (ctx,query)=>{
    catalogue=sourceCatalogue(ctx.sessionManager.getBranch(),query,ctx.sessionManager.getSessionId());
    return {catalogue:catalogue.id,sources:catalogue.sources,hint:"Use catalogue + S refs in context_notes.state. Exact id values still work. Original sources must support each claim."};
  };
}
