"""Strict ASCII OpenFOAM field reader.

Verbatim copy of validation/canonical_reference/foamio.py (frozen authority).
No behavioural change; duplicated so the parameterized pipeline never imports
from the frozen reference tree.
"""
import re
import numpy as np
def field(path,key='internalField',count=None,vector=False):
 text=path.read_text()
 if not re.search(r'format\s+ascii\s*;',text):raise ValueError(f'ASCII required: {path}')
 return value(text,key,count,vector)
def value(text,key='internalField',count=None,vector=False):
 m=re.search(r'\b'+re.escape(key)+r'\s+nonuniform\s+List<(scalar|vector)>\s+(\d+)\s*\((.*?)\)\s*;',text,re.S)
 if m:
  a=np.fromstring(m[3].replace('(',' ').replace(')',' '),sep=' ')
  n=int(m[2]);dim=3 if m[1]=='vector' else 1
  if a.size!=n*dim:raise ValueError('Field size mismatch')
  return a.reshape(n,3) if dim==3 else a
 m=re.search(r'\b'+re.escape(key)+r'\s+uniform\s+([^;]+);',text)
 if not m or count is None:raise ValueError(f'Cannot read {key}')
 a=np.fromstring(m[1].replace('(',' ').replace(')',' '),sep=' ')
 return np.tile(a,(count,1)) if vector else np.full(count,a[0])
def table(path):
 lines=[s for s in path.read_text().splitlines() if s.strip() and not s.startswith('#')]
 a=np.array([np.fromstring(s.replace('(',' ').replace(')',' '),sep=' ') for s in lines])
 if a.ndim!=2 or not np.isfinite(a).all():raise ValueError(f'Invalid monitor: {path}')
 return a
