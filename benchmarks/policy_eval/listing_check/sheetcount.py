import sys, os, json, statistics as st
sys.path.insert(1, os.path.expanduser('~/dev/cuga-eval/benchmarks/automationbench'))
import ab_env
ids = [x['task'] for x in json.load(open(os.path.expanduser('~/dev/cuga-eval/benchmarks/automationbench/policy_types_fresh3.json')))['tasks']]
t = ab_env.load_task(ids[0]); fns = ab_env.toolset_functions('full', t['info'])
print([f.__name__ for f in fns if f.__name__.startswith('google_sheets') and any(k in f.__name__ for k in ('list','get','find','lookup','read'))])
ws=[]; ss=[]
for tid in ids:
    w,_,_ = ab_env.build_world(ab_env.load_task(tid)['info'])
    g = w.google_sheets.model_dump()
    sp = [v for v in g.values() if isinstance(v, list)]
    print(tid, {k: len(v) for k, v in g.items() if isinstance(v,(list,dict))}) if tid==ids[0] else None
    n_ss = len(g.get('spreadsheets', [])); n_ws = len(g.get('worksheets', [])) or sum(len(s.get('worksheets', [])) for s in g.get('spreadsheets', []))
    ss.append(n_ss); ws.append(n_ws)
print('spreadsheets median/max', st.median(ss), max(ss), '| worksheets median/max', st.median(ws), max(ws))
