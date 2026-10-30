#!/usr/bin/env python3
"""Remove only unchanged managed launchers. Preserve accounts, memory and sessions."""
import argparse
import hashlib
import json
import os
from pathlib import Path


def remove_launchers(prefix):
    manifest=json.loads((prefix/'installation.json').read_text())
    targets=[]
    for name,expected in manifest['launchers'].items():
        file=Path(name)
        if not file.exists():continue
        if file.name not in ('omp-kit','graphify-kit','omp-kit.cmd','graphify-kit.cmd') or file.is_symlink() or 'omp-context-kit managed launcher' not in file.read_text(encoding='utf-8')[:180]:
            raise SystemExit('Unrecognized launcher in manifest; no files removed')
        if hashlib.sha256(file.read_bytes()).hexdigest()!=expected:raise SystemExit(f'Launcher was modified; no files removed: {file}')
        targets.append(file)
    for file in targets:file.unlink()
    return len(targets)


def main():
    default=(Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'AppData/Local')))/'OmpContextKit') if os.name=='nt' else Path(os.environ.get('XDG_DATA_HOME',str(Path.home()/'.local/share')))/'omp-context-kit'
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--prefix',type=Path,default=default);args=parser.parse_args()
    count=remove_launchers(args.prefix)
    print(f'Removed {count} managed launchers. Accounts, memory, sessions and application files remain at {args.prefix}. Existing OMP is unchanged. PATH entries may remain harmlessly in shell settings.')


if __name__=='__main__':main()
