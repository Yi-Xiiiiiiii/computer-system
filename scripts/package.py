#!/usr/bin/env python3
"""Create a reviewable upload archive, excluding binaries and Python caches."""
import argparse
import hashlib
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parents[1]
def main():
    p=argparse.ArgumentParser(); p.add_argument('--out',type=Path,required=True); a=p.parse_args()
    if ROOT in a.out.resolve().parents: raise ValueError('Place the archive outside the source folder')
    files=[x for x in sorted(ROOT.rglob('*')) if x.is_file() and
           not any(part in ('build','__pycache__','.git') for part in x.relative_to(ROOT).parts) and
           not x.name.endswith('.pyc') and x.name!='MANIFEST.sha256']
    manifest=ROOT/'MANIFEST.sha256'
    manifest.write_text(''.join(hashlib.sha256(x.read_bytes()).hexdigest()+'  '+x.relative_to(ROOT).as_posix()+'\n' for x in files))
    a.out.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(a.out,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for path in [*files,manifest]: z.write(path,Path(ROOT.name)/path.relative_to(ROOT))
    print(f'{len(files)+1} files: {a.out} ({a.out.stat().st_size} bytes)')

if __name__=='__main__': main()
