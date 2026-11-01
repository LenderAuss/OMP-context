// OMP 18.14 selects notebook-only rollover only when all four required tools
// are active. With new_context excluded, its normal summary pipeline owns
// automatic, mid-turn, overflow and manual compaction. Native context_notes
// and history://current/full remain available (the setting stays enabled).
// Do not synthesize compaction entries, start another model, or cancel native
// summaries because an optional cross-session checkpoint is missing.
export function installCompaction(pi) {
  const ensureSummaryMode = async () => {
    const active = pi.getActiveTools();
    if (!active.includes("new_context")) return false;
    await pi.setActiveTools(active.filter(name => name !== "new_context"));
    return true;
  };
  for (const event of ["session_start", "session_branch", "session_tree"])
    pi.on(event, ensureSummaryMode);
  pi.on("session_before_compact", async (_event, ctx) => {
    // A settings/tool-surface change can re-enable rollover during a live
    // turn. Cancel that one unsafe pass; the next native pass uses summaries.
    if (await ensureSummaryMode()) {
      if (ctx.hasUI) ctx.ui.notify("Включено штатное сжатие с резюме; сохранение заметок его не блокирует.", "info");
      return {cancel:true};
    }
  });
  pi.on("session.compacting", () => ({context:[
    "Preserve the current user goal, restrictions, corrected or rejected decisions, completed work with evidence, changed file paths, unresolved blockers, and exact next steps. Separate verified results from plans. Treat context_notes as dated observations; later original messages take precedence. If information is missing, state that explicitly. Keep unfinished work resumable without repeating completed actions. Original messages remain in history://current/full; use bounded retrieval when needed."
  ]}));
  return ensureSummaryMode;
}
