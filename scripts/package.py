#!/usr/bin/env python3
"""Build a deterministic source distribution from an explicit public allowlist."""
import argparse
import gzip
import hashlib
import io
from pathlib import Path
import re
import tarfile
import zipfile

ROOT=Path(__file__).resolve().parents[1]
FILES=['README.md','LICENSE','THIRD_PARTY_NOTICES.md','AGENTS.md','package.json','requirements.in','requirements.lock','versions.lock.json','install.py','install.sh','install.ps1','launcher.py','uninstall.py','.gitignore']
DIRECTORIES=['runtime','config','tests','scripts','docs','.github']


def files():
    result=[ROOT/name for name in FILES]
    for name in DIRECTORIES:
        result.extend(p for p in (ROOT/name).rglob('*') if p.is_file() and '__pycache__' not in p.parts and not p.name.endswith('.local.json'))
    return sorted(set(result))


def check(paths):
    for file in paths:
        relative=file.relative_to(ROOT).as_posix()
        if file.is_symlink() or file.suffix in ('.db','.sqlite3','.sqlite','.jsonl','.pem','.key','.pyc') or file.name.startswith('.env'):
            raise ValueError(f'Private/runtime file in source bundle: {relative}')
        data=file.read_bytes()
        if len(data)>2*1024*1024:raise ValueError(f'Unexpected large source artifact: {relative}')
        text=data.decode('utf-8')
        if re.search(r'/Users/[A-Za-z0-9_.-]+/|/home/[A-Za-z0-9_.-]+/',text):raise ValueError(f'Personal absolute path in {relative}')
        if re.search(r'gh[pousr]_[A-Za-z0-9_]{24,}|sk-[A-Za-z0-9_-]{24,}|-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----',text):
            raise ValueError(f'Potential credential in {relative}')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--check',action='store_true');args=parser.parse_args()
    paths=files();check(paths)
    if args.check:print(f'Public source allowlist and sensitive-path scan passed: {len(paths)} files');return
    out=ROOT/'dist';out.mkdir(exist_ok=True)
    stem='omp-context-kit-0.1.0';zip_path=out/(stem+'.zip');tar_path=out/(stem+'.tar.gz')
    with zipfile.ZipFile(zip_path,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        for p in paths:
            info=zipfile.ZipInfo(stem+'/'+p.relative_to(ROOT).as_posix(),date_time=(1980,1,1,0,0,0))
            info.external_attr=((0o100755 if p.suffix in ('.sh','.py') else 0o100644)<<16)
            archive.writestr(info,p.read_bytes(),compress_type=zipfile.ZIP_DEFLATED)
    with tar_path.open('wb') as raw,gzip.GzipFile(filename='',mode='wb',fileobj=raw,mtime=0) as compressed,tarfile.open(fileobj=compressed,mode='w') as archive:
        for p in paths:
            data=p.read_bytes();info=tarfile.TarInfo(stem+'/'+p.relative_to(ROOT).as_posix());info.size=len(data);info.mtime=0;info.mode=0o755 if p.suffix in ('.sh','.py') else 0o644
            archive.addfile(info,io.BytesIO(data))
    sums=[]
    for p in (zip_path,tar_path):
        sums.append(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name)
        print(p.name,p.stat().st_size,'bytes')
    (out/'SHA256SUMS.txt').write_text('\n'.join(sums)+'\n')


if __name__=='__main__':main()
