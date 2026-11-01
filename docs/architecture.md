# Architecture and verification boundaries

## Storage and request flow

`omp-kit` → private OMP profile → native summary compaction + separate sourced cross-session memory.

Version 0.1.2 removes the checkpoint veto and its stop-hook repair continuation. In 0.1.1 two rejected notebook writes could leave every rollover cancelled indefinitely while the conversation kept growing. Checkpoint validity must not be a prerequisite for preserving a long session through a native summary.

The pinned OMP 18.14.0 selects notebook-only rollover only if `context_notes`, `new_context`, `read` and `grep` are all active. Using the supported `setActiveTools` API, the extension excludes only `new_context` at session startup, branch/tree changes and before prompts. Native notes and full branch history remain available. OMP's regular maintenance pipeline then handles threshold, mid-turn, overflow and manual compaction with its configured methods; the preset uses `shake` then `soft`. A late tool-surface change is corrected before compaction, cancelling only that unsafe rollover pass. Ordinary native summaries are never gated on notes. This capability contract is version-specific and must be integration-tested before updating OMP.

No extension writes compaction entries or starts a second compactor. The `session.compacting` hook supplies brief preservation guidance without replacing the native summary prompt. Native OMP owns summary requests, the cut point, retention of complete recent tool units, journal commits, continuation and provider-failure handling. `autoContinue` is on for new profiles; existing user configuration remains preserved. Idle compaction and cache warming stay off. A native summarizer may make multiple requests at a boundary (for example summary chunks and a short summary); these consume the selected provider's quota.

The runtime extension validates native `context_notes` before execution. A successful note is exported to a separate local SQLite database by a bounded Python child process over stdin; private payloads are never placed in command-line arguments. Each claim retains source entry IDs, a short redacted excerpt, the original session path and a source-text hash. This proves an association with an entry, not the truth of the summary.

In 0.1.1 a session-scoped source catalogue gives short aliases bound to a catalogue digest. The structured notebook wrapper expands aliases, supplies schema boilerplate, and validates the result before calling the same native `context_notes` via `ctx.invokeTool`. It does not write reserved journal entries or implement a second compactor. Legacy serialized notes still work. The wrapper registers only when native notes mode exists at session start.

Before a user prompt, local FTS5 retrieves a bounded set of records. The callback returns an evidence card with project, date, status and sources. It deduplicates against accepted journal entries, not mutable hook invocation state, so a host policy retry cannot silently discard the recall. Compaction starts a new window in which recall can be injected again.

No extra LLM performs search, embeddings, graph projection or periodic background summaries. Writing the actual checkpoint is model work in the current conversation. Rejected notes cannot block native summary compaction or create extension-owned repair loops. Structured `in_progress` is normalized to `pending`, preserving unfinished status and the v1 storage schema; catalogue IDs mistakenly used as source IDs are rejected with a targeted explanation.

## Isolation and corrections

- The memory database belongs to one local installation/user. There is no network server or device synchronization.
- Claims are associated with canonical project paths. Global user preferences need an original user source.
- Search prefers the current project, global user preferences and explicitly mentioned aliases. Cross-project fallback candidates are labelled; they are not automatically current-project instructions.
- Project filtering and ordering happen in SQL before the candidate cap. Explicit all-project search appends other candidates after scoped results; user-only search cannot fall back to projects.
- Only visible ancestor checkpoints of the same session branch are retired by a new snapshot. Sibling branches remain distinguishable.
- Explicit stable keys allow conflicting values to be flagged. Resolution names prior memory IDs in `supersedes`. Unknown semantic equivalence/contradiction is not inferred automatically.
- Model-generated summaries are `agent-noted`, not promoted to verified facts. Source roles and excerpts remain available for review.
- Original source dates are stored separately from index write time. Importing an old note today does not make the evidence current; missing source dates stay explicitly unknown.
- Recalled cards alone are refused as new independent evidence. Original user/tool evidence is required.
- Failed checkpoint export is transactional: it cannot deactivate the previous usable snapshot halfway through.
- WAL, busy timeouts and transactions serialize concurrent session writes. Schema version guards prevent silently opening a newer incompatible database.
- Forgetting removes all normalized copies within the same project, including inactive snapshots. Search, evidence and graph projection also honor legacy tombstones. Other projects and differently negated/numeric claims are preserved. Schema 2 is unchanged so an already-running 0.1.0 process remains compatible; it must be restarted to use the new retrieval logic.

## Local health metrics

`/context-health` and `context_probe(action=health)` filter the saved journal to current-branch IDs. `omp-kit health` scans the latest journal (or an explicitly named JSONL file) and labels its potentially multi-branch scope. Reading is bounded to 32 MiB, incomplete lines are counted, and a truncated report is marked partial. Only token/cache aggregates, checkpoint counters, memory-card byte counts and compaction metadata are returned. `compactions` counts all committed boundaries; `rollovers` retains its older notebook-only meaning. Journaled assistant usage can exclude native summarizer/side requests and is not total billing. Health queries create no model runs, database telemetry tables or dialogue exports. Byte counts are not token estimates.

## Common graph

SQLite is authoritative. After mutations, the helper atomically rebuilds a bounded Graphify-compatible projection containing projects, current/conflicting records and citation edges. `EXTRACTED` on a citation edge means the record cites that source; it does not certify that the claim is true. The projection carries `claims_are_not_verified: true`.

Project code/document graphs remain separate and may be stale. The extension does not treat them as authorization, executable instructions or live deployment state. Graphify traversal and the final returned text are bounded.

## Installer contract

OMP and bootstrap uv release binaries are selected by OS/architecture and checked against committed SHA-256 metadata. Graphify and its transitive packages use a universal hash lock and binary wheels. No third-party `curl | sh` installer is executed. The kit's own shell/PowerShell bootstrap downloads a verified uv binary and runs the local reviewed Python installer.

An isolated profile, managed application releases and dependency environment avoid replacing system Python or an existing OMP binary. User config is created only on first installation. Launchers are only updated if their previous hashes match. Unmanaged installation prefixes are rejected before permissions are changed. Passwords, OAuth tokens, existing account databases and original user sessions are not copied.

The default approval preset is intentionally `yolo`, matching the requested configuration; `write` and `always-ask` are available for a fresh profile. It is not a sandbox. Upstream OMP's normal provider/environment and project discovery behavior still applies.

## What tests do and do not establish

Unit tests cover checksum rejection, platform selection, shell quoting, PATH idempotence, input limits, source IDs, branch/reset boundaries, supersession, provenance, secret redaction, forgotten-memory tombstones, negation-preserving identity, concurrency and database transaction rollback.

The loopback integration tests use real OMP processes, extension lifecycle and actual tools. One verifies automatic persistence/recall across two independent sessions. Another reproduces invalid aliases and catalogue-as-source failures, crosses the automatic threshold twice across process restart/resume, verifies native summary commits, continuation without user intervention, retained original entry IDs and full-history retrieval. Neither depends on a paid model's behavior. The optional live test separately measures whether a selected model follows the checkpoint/recall workflow on a synthetic scenario.

These tests do not establish long-run factual completeness, token savings on arbitrary projects, all possible provider quirks, or an operating system that has not run them. Native notes/full-history support remains experimental upstream. Provider failure, disabled maintenance, oversized fixed prompts or single indivisible tool units can still prevent compaction; the extension does not override the host's failure handling. A graph or valid source ID never substitutes for inspecting the current source or obtaining real authorization for an external action.
