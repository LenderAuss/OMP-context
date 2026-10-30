export const NOTE_TYPE = "experimental_context_notes";
export const MAX_BYTES = 12_288;

export function activeBranch(entries) {
  const boundary = entries.findLastIndex(e => e.type === "reset_boundary");
  return entries.slice(boundary + 1);
}

export function latestNote(entries) {
  return activeBranch(entries).findLast(e => e.type === "custom" && e.customType === NOTE_TYPE);
}

const array = Array.isArray;
const text = x => typeof x === "string" && x.trim().length > 0;
const record = x => x !== null && typeof x === "object" && !array(x);

// This checks provenance and structure, not whether a model's summary is true or complete.
export function validateCheckpoint(raw, entries) {
  const errors = [];
  if (typeof raw !== "string" || Buffer.byteLength(raw, "utf8") > MAX_BYTES)
    return { ok: false, errors: [`Checkpoint must be a JSON string of at most ${MAX_BYTES} UTF-8 bytes.`] };
  let state;
  try { state = JSON.parse(raw); }
  catch { return { ok: false, errors: ["Checkpoint must be valid JSON, without Markdown fences."] }; }
  if (!record(state)) return { ok: false, errors: ["Checkpoint must be a JSON object."] };
  if (state.version !== 1) errors.push("version must be 1.");
  const ids = new Set(activeBranch(entries).filter(e =>
    e.type === "message" || e.type === "custom_message" || e.type === "branch_summary"
  ).map(e => e.id));
  function claim(value, path) {
    if (!record(value) || !text(value.text)) { errors.push(`${path}.text must be nonempty.`); return; }
    if (!array(value.sources) || value.sources.length < 1 || value.sources.length > 8) {
      errors.push(`${path}.sources must contain 1–8 exact entry IDs from this branch.`); return;
    }
    for (const id of value.sources) if (!text(id) || !ids.has(id))
      errors.push(`${path}: source ID ${String(id).slice(0, 80)} does not identify a source entry on this branch.`);
  }
  claim(state.goal, "goal");
  for (const key of ["constraints", "decisions", "progress"]) {
    if (!array(state[key]) || state[key].length > 40) {
      errors.push(`${key} must be an array with at most 40 items.`); continue;
    }
    state[key].forEach((item, i) => claim(item, `${key}[${i}]`));
  }
  const decisions = new Map();
  for (const item of array(state.decisions) ? state.decisions : []) {
    if (!record(item)) continue;
    if (!text(item.id) || decisions.has(item.id)) errors.push("Decision IDs must be nonempty and unique.");
    else decisions.set(item.id, item);
    if (!["active", "superseded", "rejected"].includes(item.status)) errors.push("Decision status must be active, superseded, or rejected.");
  }
  for (const item of decisions.values()) {
    if (item.supersedes !== undefined && item.supersedes !== null && (!decisions.has(item.supersedes) || item.supersedes === item.id || decisions.get(item.supersedes)?.status !== "superseded"))
      errors.push(`Decision ${item.id}: supersedes must refer to another decision marked superseded.`);
  }
  for (const item of array(state.progress) ? state.progress : [])
    if (!record(item) || !["done", "pending", "blocked"].includes(item.status)) errors.push("Progress status must be done, pending, or blocked.");
  for (const key of ["next", "questions"]) {
    if (!array(state[key]) || state[key].length > 20 || state[key].some(x => !text(x)))
      errors.push(`${key} must be an array of at most 20 nonempty strings (empty array is allowed).`);
  }
  return { ok: errors.length === 0, errors: errors.slice(0, 8), state };
}

function substantive(e) {
  if (e.type === "custom_message") return true;
  if (e.type !== "message") return false;
  const m = e.message ?? {};
  if (m.role === "toolResult") return !["context_notes", "context_probe", "new_context"].includes(m.toolName);
  if (m.role === "assistant") {
    const blocks = array(m.content) ? m.content : [];
    const calls = blocks.filter(b => b.type === "toolCall");
    if (calls.length && calls.every(b => ["context_notes", "context_probe", "new_context"].includes(b.name))) return false;
    return blocks.some(b => b.type === "text" && text(b.text)) || blocks.some(b => b.type === "toolCall" && !["context_notes", "context_probe", "new_context"].includes(b.name));
  }
  return ["user", "developer", "bashExecution", "pythonExecution"].includes(m.role);
}

export function checkpointGate(entries, firstKeptEntryId) {
  const branch = activeBranch(entries);
  const note = latestNote(branch);
  if (!note) return { ok: false, errors: ["No checkpoint exists. Save context_notes before rolling over."], note };
  const valid = validateCheckpoint(note.data?.text, branch);
  if (!valid.ok) return { ...valid, note };
  const noteIndex = branch.findIndex(e => e.id === note.id);
  const keptIndex = firstKeptEntryId ? branch.findIndex(e => e.id === firstKeptEntryId) : -1;
  // Compaction may discard only work older than the checkpoint. Newer work is safe in the retained tail.
  const cutoff = keptIndex >= 0 ? keptIndex : branch.length;
  const uncovered = branch.slice(noteIndex + 1, cutoff).filter(substantive);
  if (uncovered.length) return { ok: false, note, errors: [`Checkpoint is older than ${uncovered.length} source entries that may leave context. Update it first.`] };
  return { ...valid, note };
}

export function sources(entries, query = "", limit = 12) {
  const needle = query.toLocaleLowerCase();
  return activeBranch(entries).filter(e => ["message", "custom_message", "branch_summary"].includes(e.type))
    .map(e => {
      const m = e.message ?? e;
      const body = typeof m.content === "string" ? m.content : array(m.content)
        ? m.content.filter(b => b.type === "text").map(b => b.text).join("\n") : e.summary ?? "";
      return { id: e.id, role: m.role ?? e.type, tool: m.toolName, body };
    }).filter(e => !needle || e.body.toLocaleLowerCase().includes(needle) || e.id.includes(query))
    .slice(-limit).map(({body, ...e}) => ({...e, preview: body.slice(0, 240)}));
}
