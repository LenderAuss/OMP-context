#!/usr/bin/env python3
"""Installed launcher's private entry point. Account login stays inside native OMP."""
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    prefix = Path(sys.argv[1])
    manifest = json.loads((prefix / "installation.json").read_text(encoding="utf-8"))
    args = sys.argv[2:]
    env = os.environ.copy()
    env.update(PI_CODING_AGENT_DIR=manifest["agentDir"], OMP_KIT_PYTHON=manifest["python"],
               OMP_KIT_MEMORY_DB=manifest["memoryDb"], OMP_KIT_GRAPHIFY=manifest["graphify"], PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    if args and args[0] == "doctor":
        checks = {}
        for label, command in [("omp", [manifest["omp"], "--version"]),
                               ("graphify", [manifest["graphify"], "--version"]),
                               ("python", [manifest["python"], "-c", "import sqlite3,graphify; c=sqlite3.connect(':memory:');c.execute('CREATE VIRTUAL TABLE test USING fts5(text)');print('SQLite FTS5 + Graphify OK')"])]:
            result = subprocess.run(command, env=env, text=True, capture_output=True)
            checks[label] = {"ok": result.returncode == 0, "version": result.stdout.strip()[:160]}
        checks["config"] = {"ok": (Path(manifest["agentDir"]) / "config.yml").is_file()}
        print(json.dumps({"checks": checks, "state": str(prefix / "state"), "credentials_checked": False}, indent=2))
        return int(not all(check["ok"] for check in checks.values()))
    if args and args[0] in ("memory", "health"):
        action = "health" if args[0] == "health" else args[1] if len(args) > 1 else "status"
        if action not in ("status", "search", "evidence", "forget", "graph", "health"):
            raise SystemExit("Usage: omp-kit memory status|search <query>|evidence <id>|forget <id>|graph")
        request = {"action": action, "project": os.getcwd()}
        if action == "health":
            if args[0] != "health" or len(args) > 2:
                raise SystemExit("Usage: omp-kit health [session.jsonl]")
            request.update(agent_dir=manifest["agentDir"], file=args[1] if len(args) == 2 else None)
        if action == "search":
            request["query"] = " ".join(args[2:])
            request["scope"] = "all"
        if action in ("evidence", "forget"):
            if len(args) != 3:
                raise SystemExit("A memory ID is required")
            request["id"] = args[2]
        result = subprocess.run([manifest["python"], str(Path(manifest["app"]) / "runtime/python/memory.py")], input=json.dumps(request), text=True, encoding="utf-8", env=env, capture_output=True)
        try:
            print(json.dumps(json.loads(result.stdout), indent=2, ensure_ascii=False))
        except ValueError:
            print("Memory helper failed; no request contents printed.", file=sys.stderr)
        return result.returncode
    if args and args[0] == "graphify":
        return subprocess.call([manifest["graphify"], *args[1:]], env=env)
    # No shell interpolation; arbitrary provider flags and interactive /login are passed through.
    return subprocess.call([manifest["omp"], *args], env=env)


if __name__ == "__main__":
    raise SystemExit(main())
