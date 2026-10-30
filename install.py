#!/usr/bin/env python3
"""Checksum-pinned, isolated OMP + Graphify installer. Standard library only."""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

SOURCE = Path(__file__).resolve().parent
MARKER = "omp-context-kit managed launcher"


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def target_platform(system=None, machine=None, musl=None):
    system = system or platform.system()
    machine = (machine or platform.machine()).lower()
    arch = {"arm64": "arm64", "aarch64": "arm64", "amd64": "x64", "x86_64": "x64"}.get(machine)
    if not arch:
        raise ValueError(f"Unsupported architecture: {machine}; 64-bit x86 or ARM is required")
    if system == "Windows":
        # Graphify's native language wheels target Windows x64; Windows ARM uses x64 compatibility.
        return "windows-x64"
    if system == "Darwin":
        return "darwin-" + arch
    if system == "Linux":
        if musl is None:
            musl = Path("/etc/alpine-release").exists() or bool(list(Path("/lib").glob("ld-musl-*.so*")))
        return "linux-" + ("musl-" if musl else "") + arch
    raise ValueError("Supported operating systems: macOS, Linux/WSL, Windows")


def default_prefix():
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local"))) / "OmpContextKit"
    return Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "omp-context-kit"


def atomic_text(path, content, mode=0o600):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".kit-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def verified_asset(asset, destination, local=None):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and sha(destination) == asset["sha256"]:
        return destination
    if not asset["url"].startswith("https://github.com/"):
        raise ValueError("Binary download must use a pinned HTTPS GitHub release URL")
    fd, temporary = tempfile.mkstemp(prefix=".download-", dir=destination.parent)
    try:
        with os.fdopen(fd, "wb") as out:
            source = open(local, "rb") if local else urllib.request.urlopen(asset["url"], timeout=60)
            with source:
                shutil.copyfileobj(source, out)
        if sha(temporary) != asset["sha256"]:
            raise ValueError("Binary SHA-256 mismatch; refused to execute or replace the installed binary")
        os.chmod(temporary, 0o755)
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return destination


def run(args, **kwargs):
    result = subprocess.run([str(x) for x in args], text=True, **kwargs)
    if result.returncode:
        raise RuntimeError(f"Command failed ({result.returncode}): {Path(str(args[0])).name} {args[1] if len(args)>1 else ''}")
    return result


@contextlib.contextmanager
def installation_lock(prefix):
    lock = open(prefix / ".install.lock", "a+b")
    try:
        if os.name == "nt":
            import msvcrt
            if not lock.tell():
                lock.write(b"0"); lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as error:
        lock.close()
        raise RuntimeError("Another installation is running for this prefix") from error
    try:
        yield
    finally:
        lock.close()


def private_directory(prefix):
    prefix.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != "nt":
        os.chmod(prefix, 0o700)
    else:
        # Protect this installation directory only, never a shared parent directory.
        import csv
        identity = run(["whoami", "/user", "/fo", "csv", "/nh"], capture_output=True).stdout.strip()
        sid = next(csv.reader([identity]))[-1]
        if not sid.startswith("S-1-"):
            raise RuntimeError("Could not resolve the current Windows user SID")
        run(["icacls", prefix, "/inheritance:r", "/grant:r", f"*{sid}:(OI)(CI)F", "*S-1-5-18:(OI)(CI)F"], capture_output=True)


def source_files():
    roots = ["runtime", "config"]
    files = [SOURCE / x for x in ("launcher.py", "versions.lock.json", "requirements.lock", "package.json")]
    for root in roots:
        files.extend(p for p in (SOURCE / root).rglob("*") if p.is_file() and "__pycache__" not in p.parts and not p.name.endswith(".local.json"))
    return sorted(files)


def install_app(prefix):
    files = source_files()
    identity = hashlib.sha256("\n".join(str(p.relative_to(SOURCE)) + ":" + sha(p) for p in files).encode()).hexdigest()[:16]
    app = prefix / "releases" / ("0.1.0-" + identity)
    if not app.exists():
        app.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=".app-", dir=app.parent))
        try:
            for file in files:
                target = temporary / file.relative_to(SOURCE)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(file, target)
            os.replace(temporary, app)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
    for file in files:
        if sha(app / file.relative_to(SOURCE)) != sha(file):
            raise ValueError("An installed application file was modified; refusing to overwrite it")
    return app


def launcher_text(python, app, prefix, windows=False, graph=False):
    if windows:
        # Windows cmd expands % even inside quotes; reject exotic install paths rather than mis-executing them.
        values = [str(python), str(app / "launcher.py"), str(prefix)]
        if any(any(c in value for c in '%!\r\n"') for value in values):
            raise ValueError('Windows installation paths cannot contain %, !, quotes or newlines')
        return (f'@echo off\r\nrem {MARKER}\r\nsetlocal\r\n'
                'for /f "tokens=2 delims=:" %%a in (\'chcp\') do set "_OMP_KIT_CP=%%a"\r\n'
                'chcp 65001 >nul\r\n'
                f'"{values[0]}" "{values[1]}" "{values[2]}" ' + ("graphify " if graph else "") + '%*\r\n'
                'set "_OMP_KIT_EXIT=%ERRORLEVEL%"\r\n'
                'chcp %_OMP_KIT_CP% >nul\r\n'
                'exit /b %_OMP_KIT_EXIT%\r\n')
    args = " ".join(shlex.quote(str(x)) for x in [python, app / "launcher.py", prefix])
    return f'#!/bin/sh\n# {MARKER}\nexec {args} ' + ("graphify " if graph else "") + '"$@"\n'


def update_path(bin_dir, home=None, windows=None, shell=None):
    windows = os.name == "nt" if windows is None else windows
    if windows:
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            try:
                current, kind = winreg.QueryValueEx(key, "Path")
            except FileNotFoundError:
                current, kind = "", winreg.REG_EXPAND_SZ
            if str(bin_dir).lower() not in [x.rstrip("\\").lower() for x in current.split(";")]:
                winreg.SetValueEx(key, "Path", 0, kind, current.rstrip(";") + ";" + str(bin_dir))
        return "User PATH updated; open a new terminal"
    home = Path(home or Path.home())
    shell = shell or Path(os.environ.get("SHELL", "/bin/sh")).name
    if shell == "fish":
        return "fish: add the printed bin directory with fish_add_path"
    names = [".zshrc"] if shell == "zsh" else [".profile", ".bashrc"] if shell == "bash" else [".profile"]
    line = f"export PATH={shlex.quote(str(bin_dir))}:\"$PATH\" # omp-context-kit PATH"
    for name in names:
        file = home / name
        original = file.read_text() if file.exists() else ""
        if line not in original.splitlines():
            with file.open("a", encoding="utf-8") as stream:
                stream.write("\n" + line + "\n")
    return "Shell startup PATH updated; open a new terminal"


def install(args):
    lock = json.loads((SOURCE / "versions.lock.json").read_text())
    target = target_platform()
    asset_name = "omp-" + target + (".exe" if target.startswith("windows") else "")
    prefix = args.prefix.expanduser().resolve()
    bin_dir = (args.bin_dir or (prefix / "bin" if os.name == "nt" else Path.home() / ".local/bin")).expanduser().resolve()
    if prefix == Path.home() or prefix == Path(prefix.anchor):
        raise ValueError("Choose a dedicated installation directory, not the home or filesystem root")
    plan = {"platform":target,"prefix":str(prefix),"binDir":str(bin_dir),"omp":lock["omp"]["version"],"graphify":lock["graphify"]["version"],"permissionsForNewProfile":args.permissions,"existingAccounts":"not copied","memory":"local only"}
    if args.dry_run:
        print(json.dumps(plan, indent=2));return
    if prefix.exists() and any(prefix.iterdir()) and not (prefix / "installation.json").is_file() and not (prefix / ".installing").exists():
        raise ValueError("Installation prefix is not empty and is not managed by this installer")
    private_directory(prefix)
    with installation_lock(prefix):
        old_file = prefix / "installation.json"
        previous = json.loads(old_file.read_text()) if old_file.is_file() else None
        if not previous and any(prefix.iterdir()) and any(x.name not in (".install.lock", ".installing") for x in prefix.iterdir()):
            if not (prefix / ".installing").exists():
                raise ValueError("Installation prefix is not empty and is not managed by this installer")
        (prefix / ".installing").touch(mode=0o600)
        print(json.dumps(plan, indent=2), flush=True)
        uv = args.uv or shutil.which("uv")
        if not uv:
            raise RuntimeError("uv not found; use install.sh or install.ps1 for automatic bootstrap")
        omp = verified_asset(lock["omp"]["assets"][asset_name], prefix / "tools" / lock["omp"]["version"] / asset_name, args.omp_binary)
        if platform.system() == "Darwin":
            run(["codesign", "--verify", "--strict", str(omp)], capture_output=True)
        run([omp, "--version"])
        run([uv, "python", "install", lock["python"], "--no-config"])
        python_base = run([uv, "python", "find", "--managed-python", lock["python"], "--no-config"], capture_output=True).stdout.strip()
        environment = prefix / "environments" / ("graphify-" + sha(SOURCE / "requirements.lock")[:12])
        python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        if not python.exists():
            run([uv, "venv", environment, "--python", python_base, "--no-config"])
        run([uv, "pip", "sync", SOURCE / "requirements.lock", "--python", python, "--require-hashes", "--only-binary", ":all:", "--index-url", "https://pypi.org/simple", "--no-config"])
        graphify = environment / ("Scripts/graphify.exe" if os.name == "nt" else "bin/graphify")
        run([graphify, "--version"])
        run([python, "-c", "import sqlite3,graphify;c=sqlite3.connect(':memory:');c.execute('CREATE VIRTUAL TABLE test USING fts5(text)')"])
        app = install_app(prefix)
        state = prefix / "state"
        agent = state / "agent"
        agent.mkdir(parents=True, exist_ok=True, mode=0o700)
        memory_db = state / "memory.sqlite3"
        runtime_config = {"python":str(python),"memoryDb":str(memory_db),"graphify":str(graphify)}
        atomic_text(app / "runtime/runtime.local.json", json.dumps(runtime_config, indent=2))
        config = agent / "config.yml"
        if not config.exists():
            atomic_text(config, (SOURCE / "config/config.yml").read_text().replace("approvalMode: yolo", "approvalMode: " + args.permissions))
        else:
            print("Existing profile configuration preserved.")
        loader = agent / "extensions/context-kit.js"
        if loader.exists() and "omp-context-kit" not in loader.read_text()[:160]:
            raise ValueError("Extension path is occupied by a file not managed by this installer")
        loader_content = "// omp-context-kit managed extension\nexport { default } from " + json.dumps((app / "runtime/extension.js").as_posix()) + ";\n"
        launchers = {}
        for name, graph in [("omp-kit",False),("graphify-kit",True)]:
            file = bin_dir / (name + (".cmd" if os.name == "nt" else ""))
            if file.exists():
                old_hash = (previous or {}).get("launchers", {}).get(str(file))
                if not old_hash or sha(file) != old_hash:
                    raise ValueError(f"Launcher {file.name} already exists or was edited; choose --bin-dir")
            content = launcher_text(python, app, prefix, windows=os.name=="nt", graph=graph)
            launchers[str(file)] = content
        manifest = {"version":"0.1.0","installed":time.time(),"platform":target,"app":str(app),"python":str(python),"omp":str(omp),"graphify":str(graphify),"agentDir":str(agent),"memoryDb":str(memory_db),"launchers":{}}
        if previous:
            atomic_text(prefix / "backups" / f"installation-{time.time_ns()}.json", json.dumps(previous, indent=2))
        # All downloads and runtime checks have passed before changing launchers.
        atomic_text(loader, loader_content)
        for file, content in launchers.items():
            atomic_text(Path(file), content, 0o755)
            manifest["launchers"][file] = sha(file)
        atomic_text(old_file, json.dumps(manifest, indent=2))
        (prefix / ".installing").unlink(missing_ok=True)
        if not args.no_path:
            print(update_path(bin_dir))
        env = {**os.environ,"OMP_KIT_MEMORY_DB":str(memory_db)}
        run([python, app / "runtime/python/memory.py"], input='{"action":"status"}', env=env, capture_output=True)
        run([python, app / "launcher.py", prefix, "doctor"])
        print(f"\nInstalled. Run: {bin_dir / ('omp-kit.cmd' if os.name == 'nt' else 'omp-kit')}\nInside OMP: /login, then /model. Z.AI Coding Plan: /login zai.\nNo account credentials or private memory were included in this package.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, default=default_prefix())
    parser.add_argument("--bin-dir", type=Path)
    parser.add_argument("--uv", help="uv executable (bootstrapped automatically by install.sh/install.ps1)")
    parser.add_argument("--omp-binary", type=Path, help="Reuse a local OMP binary only if it matches the pinned SHA-256")
    parser.add_argument("--permissions", choices=["yolo","write","always-ask"], default="yolo", help="Initial profile approvals; yolo matches the context preset and auto-approves tool execution")
    parser.add_argument("--no-path", action="store_true", help="Do not edit shell startup files or Windows user PATH")
    parser.add_argument("--dry-run", action="store_true")
    install(parser.parse_args())


if __name__ == "__main__":
    os.umask(0o077)
    try:
        main()
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Install failed: {error}", file=sys.stderr)
        raise SystemExit(1)
