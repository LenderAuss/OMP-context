"""Read-only journal metrics. Never return dialogue text or make model calls."""
import json
from pathlib import Path

MAX_SCAN = 32 * 1024 * 1024
FIELDS = ("input", "output", "cacheRead", "cacheWrite", "totalTokens")


def count(value):
    return value if isinstance(value, (int, float)) and value >= 0 else 0


def text_content(value):
    if isinstance(value, str):
        return value
    return "\n".join(b.get("text", "") for b in value or [] if isinstance(b, dict) and b.get("type") == "text")


def summarize(entries):
    totals = dict.fromkeys(FIELDS, 0)
    result = {"model_requests": 0, "usage_missing": 0, "provider_errors": 0, "by_model": {},
              "checkpoint_write_requests": 0, "checkpoint_saves": 0, "context_notes_errors": 0,
              "recall_cards": 0, "recall_utf8_bytes": 0, "rollovers": 0, "latest_rollover": None}
    pending_rollover = None
    for entry in entries:
        message = entry.get("message", {})
        if message.get("role") == "assistant":
            usage = message.get("usage")
            if isinstance(usage, dict):
                result["model_requests"] += 1
                values = {k: count(usage.get(k)) for k in FIELDS}
                name = str(message.get("provider", "unknown")) + "/" + str(message.get("model", "unknown"))
                model = result["by_model"].setdefault(name, {"requests": 0, **dict.fromkeys(FIELDS, 0)})
                model["requests"] += 1
                for key in FIELDS:
                    totals[key] += values[key]; model[key] += values[key]
                result["latest_request"] = {"time": entry.get("timestamp"), **values}
                if pending_rollover is not None:
                    pending_rollover["next_request_input"] = values["input"] + values["cacheRead"] + values["cacheWrite"]
                    pending_rollover = None
            else:
                result["usage_missing"] += 1
            result["provider_errors"] += message.get("stopReason") == "error"
            for block in message.get("content", []) if isinstance(message.get("content"), list) else []:
                if block.get("type") == "toolCall" and block.get("name") == "context_notes":
                    arguments = block.get("arguments", {})
                    if isinstance(arguments, dict) and ("text" in arguments or "state" in arguments):
                        result["checkpoint_write_requests"] += 1
        if message.get("role") == "toolResult" and message.get("toolName") == "context_notes" and message.get("isError"):
            result["context_notes_errors"] += 1
        if entry.get("customType") == "experimental_context_notes":
            result["checkpoint_saves"] += 1
        if entry.get("customType") == "omp-context-kit.recall":
            result["recall_cards"] += 1
            result["recall_utf8_bytes"] += len(text_content(entry.get("content")).encode("utf-8"))
        if entry.get("type") == "compaction" and entry.get("details", {}).get("kind") == "experimental-context-rollover":
            result["rollovers"] += 1
            result["latest_rollover"] = {"time": entry.get("timestamp"), "tokens_before": entry.get("tokensBefore")}
            pending_rollover = result["latest_rollover"]
    total_input = totals["input"] + totals["cacheRead"] + totals["cacheWrite"]
    result.update(reported_tokens=totals, reported_input_total=total_input,
                  cache_read_share_percent=round(100 * totals["cacheRead"] / total_input, 2) if total_input else None,
                  limitations="Provider-reported usage, not a bill. Recall bytes are not tokens and do not measure repeated context processing. No causal savings estimate or dialogue text is included.")
    return result


def report(request):
    name = request.get("file")
    if not name and request.get("agent_dir"):
        sessions = list((Path(request["agent_dir"]) / "sessions").rglob("*.jsonl"))
        name = max(sessions, key=lambda p: p.stat().st_mtime) if sessions else None
    if not name:
        raise ValueError("No saved session found yet")
    source = Path(name)
    if source.suffix != ".jsonl" or not source.is_file():
        raise ValueError("Choose a saved OMP .jsonl session")
    wanted = request.get("entry_ids")
    if wanted is not None and (not isinstance(wanted, list) or len(wanted) > 20000 or any(not isinstance(x, str) for x in wanted)):
        raise ValueError("Invalid branch entry list")
    wanted = set(wanted) if wanted is not None else None
    malformed = 0
    with source.open("rb") as stream:
        stream.seek(0, 2); size = stream.tell()
        start = max(0, size - MAX_SCAN); stream.seek(start)
        if start:
            stream.readline()
        def records():
            nonlocal malformed
            while stream.tell() < size:
                raw = stream.readline(size - stream.tell())
                try:
                    entry = json.loads(raw)
                except (ValueError, UnicodeError):
                    malformed += 1
                    continue
                if isinstance(entry, dict) and (wanted is None or entry.get("id") in wanted):
                    yield entry
        result = summarize(records())
    result.update(session=source.name, scope="active branch" if wanted is not None else "saved journal (may include branches)",
                  partial=start > 0, max_scan_bytes=MAX_SCAN, malformed_or_incomplete_lines=malformed)
    return result
