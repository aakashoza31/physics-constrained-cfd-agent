#!/usr/bin/env python3
"""Recount LLM calls, proposals and rulings from every call record in the e2e demo archive.
Run from Research/physics-constrained-cfd-agent-e2e/demo. Deduplicates per run by (stage, latency)."""
import json,glob,os,collections,re
cases=sorted(set(os.path.dirname(f).split('/history/')[0] for f in glob.glob('**/events.jsonl',recursive=True) if 'reanalysis_full' not in f and ('forward_step_2d' in f or 'nozzle' in f)))
def recs(o):
    if isinstance(o,dict):
        if o.get('is_llm') is not None: yield o
        for v in o.values(): yield from recs(v)
    elif isinstance(o,list):
        for v in o: yield from recs(v)
T=collections.Counter(); P=collections.Counter(); R=collections.Counter(); out=[]
for C in cases:
    calls={}; props={}; rul={}
    for f in glob.glob(C+'/**/*.json',recursive=True):
        if 'reanalysis' in f: continue
        try: d=json.load(open(f,encoding='utf-8-sig'))
        except Exception: continue
        for r in recs(d):
            k=(r.get('stage'),round(r.get('latency_s') or -1,3))
            calls[k]=(r.get('model'),r.get('is_llm'),r.get('ok'))
        b=os.path.basename(f)
        if b in('agent_decision.json','initial_e2e_agent_decision.json'):
            dec=d.get('decision',d); k=round(d.get('llm_call',{}).get('latency_s') or -1,3)
            props[k]=(dec.get('diagnosis'),dec.get('action'),os.path.dirname(f))
        if b in('action_validation.json','initial_e2e_action_validation.json','feedback_action_gate.json'):
            rul[(os.path.dirname(f),b)]=(d.get('action') or d.get('proposed_action'), d.get('approved'), str(d.get('reason') or d.get('reasons'))[:100])
    # events-based rulings (step family + e2e)
    ev_r=[]
    for f in glob.glob(C+'/**/events.jsonl',recursive=True):
        if 'reanalysis' in f: continue
        for l in open(f,encoding='utf-8'):
            if not l.strip(): continue
            e=json.loads(l)
            if e.get('tag')=='ACTION VALIDATOR':
                g=re.match(r'(?:Proposed action )?(\w+) (APPROVED|REJECTED)',e['message'])
                if g: ev_r.append((g[1],g[2],e.get('wall')))
    vis=len([f for f in glob.glob(C+'/**/visual_observation.json',recursive=True) if 'reanalysis' not in f])
    for k in calls: T[k[0]]+=1
    for v in props.values(): P[v[1]]+=1
    fs=None
    for n in ('feedback_summary.json',):
        p=os.path.join(C,n)
        if os.path.exists(p): fs=json.load(open(p,encoding='utf-8-sig'))
    out.append((C,len(calls),{a:b for a,b in collections.Counter(k[0] for k in calls).items()},[(v[0],v[1]) for v in props.values()],len(set(ev_r)),[(a,b) for a,b,_ in sorted(set(ev_r),key=lambda x:x[2])],vis, {k:str(v)[:120] for k,v in (fs or {}).items() if k in ('final_status','status','iterations','final_decision','terminal_status','stop_reason')}))
for o in out: print(o)
print('TOTAL calls by stage',dict(T),sum(T.values())); print('proposals',dict(P),sum(P.values()))
