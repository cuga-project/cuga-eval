"""Offline audit: does the lister reach every text of the world? (measurement only; reads the world to compare)"""
import sys, os, json, time, collections
R = os.path.expanduser('~/dev/cuga-eval-policy/benchmarks')
sys.path.insert(1, R + '/automationbench'); sys.path.insert(0, R); sys.path.insert(0, os.path.expanduser('~/dev/polisys/src'))
import ab_env
from polisys.ruleset import is_write_tool
import importlib.util
spec = importlib.util.spec_from_file_location('lst', R + '/policy_eval/harness/adapters/automationbench_listing.py'); lst = importlib.util.module_from_spec(spec); spec.loader.exec_module(lst)
from pydantic import BaseModel
def strs(o):
    if isinstance(o, dict):
        for k, v in o.items():
            if k != 'actions': yield from strs(v)
    elif isinstance(o, list):
        for v in o: yield from strs(v)
    elif isinstance(o, str) and len(o.split()) >= 4: yield o.strip()  # free text, where rules are written
which = sys.argv[1] if len(sys.argv) > 1 else 'fresh3'
if which == 'fresh3':
    ids = [x['task'] for x in json.load(open(R + '/automationbench/policy_types_fresh3.json'))['tasks']]
else:
    ids = [x['task'] for x in json.load(open(os.path.expanduser('~/dev/cuga-eval/benchmarks/automationbench/results/policy_features.json')))]
tot = collections.Counter(); hit = collections.Counter(); miss_ex = {}; calls = []; secs = []; inc = collections.Counter(); errs = 0
for tid in ids:
    t = ab_env.load_task(tid); w,_,_ = ab_env.build_world(t['info'])
    fns = ab_env.toolset_functions('full', t['info'])
    before = w.model_dump_json()
    t0 = time.perf_counter(); recs, rep = lst.list_world(fns, w, ab_env.tool_app, is_write_tool); secs.append(time.perf_counter() - t0)
    assert w.model_dump_json() == before, tid
    calls.append(rep['calls']); errs += bool(rep['errors'])
    for a in rep['incomplete']: inc[a] += 1
    for a, v in w:
        if a == 'meta' or not isinstance(v, BaseModel): continue
        want = set(strs(v.model_dump(mode='json')))
        have = set(strs(recs.get(a, []))) | set(strs([r for rr in recs.values() for r in rr]))
        for s in want:
            tot[a] += 1
            if s in have: hit[a] += 1
            else: miss_ex.setdefault(a, (tid, s[:100]))
import statistics as st
print(f'{len(ids)} tasks | read calls median {st.median(calls)} max {max(calls)} | time median {st.median(secs):.3f}s max {max(secs):.3f}s | tasks with read errors {errs} | apps with pages left {dict(inc)}')
print('app: texts reached / texts in world')
for a, n in tot.most_common():
    print(f'  {a:18s} {hit[a]:6d} / {n:6d}  {100*hit[a]/n:5.1f}%   e.g. missed: {miss_ex.get(a, "")}' if hit[a] < n else f'  {a:18s} {hit[a]:6d} / {n:6d}  100%')
