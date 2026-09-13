#!/usr/bin/env python3
from __future__ import annotations
import base64, hashlib, shutil, tarfile, tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
PARTS=ROOT/'ui-v5'/'parts'
SHA='342437ce308e251c5157173108a93a59c951e28b299b62162f7d0e91a7b21760'
FILES=(
'src/components/BleeApp.tsx',
'src/components/BleeAdvancedSettings.tsx',
'src/lib/networkConfig.ts',
'src/lib/biometric.ts',
'app/globals.css',
)
def main():
    names=[f'part{i:02d}' for i in range(4)]
    paths=[PARTS/name for name in names]
    if [p.name for p in paths if p.is_file()]!=names:
        raise SystemExit('Blee 2.5: UI bundle parts missing')
    encoded=b''.join(b''.join(p.read_bytes().split()) for p in paths)
    archive=base64.b64decode(encoded,validate=True)
    digest=hashlib.sha256(archive).hexdigest()
    if digest!=SHA:
        raise SystemExit(f'Blee 2.5: UI bundle checksum mismatch: {digest}')
    temp=Path(tempfile.mkdtemp(prefix='blee-ui-2.5-'))
    try:
        archive_path=temp/'blee-ui-v5.tar.gz'; archive_path.write_bytes(archive)
        source=temp/'source'; source.mkdir()
        with tarfile.open(archive_path,'r:gz') as tar:
            root=source.resolve()
            for member in tar.getmembers():
                target=(source/member.name).resolve()
                if not str(target).startswith(str(root)+'/') and target!=root:
                    raise SystemExit(f'Blee 2.5: unsafe UI bundle member: {member.name}')
            tar.extractall(source)
        for rel in FILES:
            src=source/rel; dst=ROOT/rel
            if not src.is_file(): raise SystemExit(f'Blee 2.5: UI bundle missing {rel}')
            dst.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(src,dst)
            print(f'Blee 2.5 UI replacement: {rel}')
    finally:
        shutil.rmtree(temp,ignore_errors=True)
if __name__=='__main__': main()
