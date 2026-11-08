"""Which records does the current polisys discovery reach at task start (snapshot polisys-db0a72c)?"""
import sys, os, json, glob
R = os.path.expanduser('~/dev/cuga-eval-policy/benchmarks')
sys.path.insert(1, R + '/automationbench'); sys.path.insert(0, os.path.expanduser('~/dev/cuga_snapshots/polisys-db0a72c/src'))
import ab_env, importlib.util
from polisys.intake import discovery_tools, DISCOVERY_QUERIES, CHANGE_QUERIES, POLICY_WORDS
spec = importlib.util.spec_from_file_location('lst', R + '/policy_eval/harness/adapters/automationbench_listing.py'); lst = importlib.util.module_from_spec(spec); spec.loader.exec_module(lst)
def key(app, r):
    for k in ('id', 'Id', 'message_id', 'ts', 'ID'):
        if r.get(k) not in (None, ''): return f"{app}|{k}|{r[k]}"
def strs(o):
    if isinstance(o, dict):
        for v in o.values(): yield from strs(v)
    elif isinstance(o, list):
        for v in o: yield from strs(v)
    elif isinstance(o, str): yield o
out = {}
for p in sorted(glob.glob('/tmp/aud/disc/records/*.json')):
    d = json.load(open(p)); t = ab_env.load_task(d['task']); w,_,_ = ab_env.build_world(t['info'])
    fns = ab_env.toolset_functions('full', t['info']); by = {f.__name__: f for f in fns}
    idx = {key(r['app'], r['record']): r['n'] for r in d['records']}
    reached = set()
    for name in discovery_tools(fns):
        app = ab_env.tool_app(by[name])
        for q in DISCOVERY_QUERIES + CHANGE_QUERIES:
            try: res = lst._decode(by[name](world=w.model_copy(deep=True), query=q))
            except Exception: continue
            for r in lst._records(res):
                n = idx.get(key(app, r))
                if n: reached.add(n)
    tier0 = sorted(r['n'] for r in d['records'] if any(POLICY_WORDS.search(s) for s in strs(r['record'])))
    out[d['task']] = {'reached': sorted(reached), 'tier0_all': tier0}
json.dump(out, open('/tmp/aud/disc/old.json', 'w'))
print('tasks', len(out), 'reached total', sum(len(v['reached']) for v in out.values()))
