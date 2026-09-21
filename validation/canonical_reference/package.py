#!/usr/bin/env python3
"""Archive every run input, field, log, and monitor with SHA256 provenance."""
from pathlib import Path
import hashlib,json,shutil,sys,zipfile
root=Path(sys.argv[1]);out=Path(sys.argv[2]);out.mkdir(parents=True,exist_ok=False)
for path in root.glob('*.json'):shutil.copy2(path,out/path.name)
for d in root.iterdir():
 if d.is_dir() and (d/'validation.json').exists():
  shutil.copy2(d/'validation.json',out/(d.name+'_validation.json'))
  shutil.copy2(d/'axial_profile.csv',out/(d.name+'_axial_profile.csv'))
hashes={}
with zipfile.ZipFile(out/'raw_cases.zip','w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
 for p in sorted(root.rglob('*')):
  if p.is_file():
   key=p.relative_to(root).as_posix();hashes[key]=hashlib.sha256(p.read_bytes()).hexdigest();z.write(p,key)
(out/'SHA256SUMS.json').write_text(json.dumps(hashes,indent=2))
print(f'Complete evidence: {out}')
