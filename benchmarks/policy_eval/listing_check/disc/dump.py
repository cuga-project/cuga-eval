"""Dump every record the lister reaches, per task (fresh3), plus the request. Task data only; no grader."""
import sys, os, json
R = os.path.expanduser('~/dev/cuga-eval-policy/benchmarks')
sys.path.insert(1, R + '/automationbench'); sys.path.insert(0, os.path.expanduser('~/dev/polisys/src'))
import ab_env, importlib.util
from polisys.ruleset import is_write_tool
spec = importlib.util.spec_from_file_location('lst', R + '/policy_eval/harness/adapters/automationbench_listing.py'); lst = importlib.util.module_from_spec(spec); spec.loader.exec_module(lst)
ids = [x['task'] for x in json.load(open(R + '/automationbench/policy_types_fresh3.json'))['tasks']]
for tid in ids:
    t = ab_env.load_task(tid); w,_,_ = ab_env.build_world(t['info'])
    fns = ab_env.toolset_functions('full', t['info'])
    recs, rep = lst.list_world(fns, w, ab_env.tool_app, is_write_tool)
    flat = [{'n': i, 'app': a, 'record': r} for i, (a, r) in enumerate(((a, r) for a, rr in recs.items() for r in rr), 1)]
    req = "\n\n".join(m['content'] for m in t['prompt'] if m['role'] == 'user')
    sysm = "\n\n".join(m['content'] for m in t['prompt'] if m['role'] == 'system')
    json.dump({'task': tid, 'request': req, 'system': sysm, 'records': flat, 'report': rep}, open(f'/tmp/aud/disc/records/{tid}.json', 'w'), default=str)
print('done', len(ids))
