# Architecture and verification boundaries

## Storage and request flow

`omp-kit` → private OMP profile → native notes-backed context windows.

The runtime extension validates native `context_notes` before execution. A successful note is exported to a separate local SQLite database by a bounded Python child process over stdin; private payloads are never placed in command-line arguments. Each claim retains source entry IDs, a short redacted excerpt, the original session path and a source-text hash. This proves an association with an entry, not the truth of the summary.

In 0.1.1 a session-scoped source catalogue gives short aliases bound to a catalogue digest. The structured notebook wrapper expands aliases, supplies schema boilerplate, and validates the result before calling the same native `context_notes` via `ctx.invokeTool`. It does not write reserved journal entries or implement a second compactor. Legacy serialized notes still work. The wrapper registers only when native notes mode exists at session start.

Before a user prompt, local FTS5 retrieves a bounded set of records. The callback returns an evidence card with project, date, status and sources. It deduplicates against accepted journal entries, not mutable hook invocation state, so a host policy retry cannot silently discard the recall. Compaction starts a new window in which recall can be injected again.

No extra LLM performs search, embeddings, graph projection or periodic background summaries. Writing the actual checkpoint is model work in the current conversation. A missing/stale checkpoint can cause one repair continuation rather than silently dropping uncaptured work.

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

`/context-health` and `context_probe(action=health)` filter the saved journal to current-branch IDs. `omp-kit health` scans the latest journal (or an explicitly named JSONL file) and labels its potentially multi-branch scope. Reading is bounded to 32 MiB, incomplete lines are counted, and a truncated report is marked partial. Only token/cache aggregates, checkpoint counters, memory-card byte counts and rollover metadata are returned. No extra model runs, hidden summarizers, database telemetry tables or dialogue exports are created. Byte counts are not token or billing estimates.

## Common graph

SQLite is authoritative. After mutations, the helper atomically rebuilds a bounded Graphify-compatible projection containing projects, current/conflicting records and citation edges. `EXTRACTED` on a citation edge means the record cites that source; it does not certify that the claim is true. The projection carries `claims_are_not_verified: true`.

Project code/document graphs remain separate and may be stale. The extension does not treat them as authorization, executable instructions or live deployment state. Graphify traversal and the final returned text are bounded.

## Installer contract

OMP and bootstrap uv release binaries are selected by OS/architecture and checked against committed SHA-256 metadata. Graphify and its transitive packages use a universal hash lock and binary wheels. No third-party `curl | sh` installer is executed. The kit's own shell/PowerShell bootstrap downloads a verified uv binary and runs the local reviewed Python installer.

An isolated profile, managed application releases and dependency environment avoid replacing system Python or an existing OMP binary. User config is created only on first installation. Launchers are only updated if their previous hashes match. Unmanaged installation prefixes are rejected before permissions are changed. Passwords, OAuth tokens, existing account databases and original user sessions are not copied.

The default approval preset is intentionally `yolo`, matching the requested configuration; `write` and `always-ask` are available for a fresh profile. It is not a sandbox. Upstream OMP's normal provider/environment and project discovery behavior still applies.

## What tests do and do not establish

Unit tests cover checksum rejection, platform selection, shell quoting, PATH idempotence, input limits, source IDs, branch/reset boundaries, supersession, provenance, secret redaction, forgotten-memory tombstones, negation-preserving identity, concurrency and database transaction rollback.

The loopback integration test uses the real OMP process, extension lifecycle, actual tools and two independent sessions. It tests transport and automatic persistence/recall without relying on a paid model's behavior. The optional live test separately measures whether a selected model follows the checkpoint/recall workflow on a synthetic scenario.

Neither establishes long-run factual completeness, token savings on arbitrary projects, all possible provider quirks, or an operating system that has not run the tests. Notes-backed windows remain an experimental upstream feature. A graph or valid source ID never substitutes for inspecting the current source or obtaining real authorization for an external action.
