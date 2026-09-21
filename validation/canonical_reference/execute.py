#!/usr/bin/env python3
"""Bounded serial execution; distinguish timeout, stall, and numerical failure."""
import json,os,re,signal,subprocess,sys,time
from pathlib import Path
case=Path(sys.argv[1]);wall_limit=float(os.environ.get('REFERENCE_WALL_LIMIT_S','7200'))
def tail(path,n=12000):
 try:
  with path.open('rb') as f:f.seek(0,2);f.seek(max(0,f.tell()-n));return f.read().decode(errors='replace')
 except FileNotFoundError:return ''
start=time.monotonic();last_progress=start;last_time=-1.;reason=None
env=os.environ.copy();env['FOAM_SIGFPE']='true'
with (case/'log.foamRun').open('w') as log:
 p=subprocess.Popen(['foamRun','-case',str(case)],stdout=log,stderr=subprocess.STDOUT,env=env,start_new_session=True)
 while p.poll() is None:
  time.sleep(2)
  now=time.monotonic();txt=tail(case/'log.foamRun');matches=re.findall(r'^Time = ([\d.eE+-]+)s',txt,re.M)
  if matches and float(matches[-1])>last_time:last_time=float(matches[-1]);last_progress=now
  mins=tail(case/'postProcessing/extrema/0/volFieldValue.dat',2000).splitlines()
  if mins and not mins[-1].startswith('#'):
   try:
    vals=[float(s) for s in mins[-1].split()]
    if len(vals)==4 and any(not (v>0 and v<float('inf')) for v in vals[1:]):reason='NONPHYSICAL'
   except ValueError:pass
  if now-start>wall_limit:reason='TIMED_OUT'
  elif now-last_progress>180:reason='STALLED'
  if reason:
   os.killpg(p.pid,signal.SIGTERM)
   try:p.wait(timeout=10)
   except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);p.wait()
   break
 code=p.wait()
elapsed=time.monotonic()-start
(case/'solver.exitcode').write_text(str(code)+'\n')
(case/'execution.json').write_text(json.dumps({'status':reason or ('COMPLETED' if code==0 else 'FAILED'),'returncode':code,'wall_seconds':elapsed,'last_observed_time':last_time,'wall_limit_seconds':wall_limit,'serial':True},indent=2))
print((case/'execution.json').read_text());sys.exit(0 if code==0 and reason is None else 3)
