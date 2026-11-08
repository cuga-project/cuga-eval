import sys, os, json, collections, inspect
sys.path.insert(1, os.path.expanduser('~/dev/cuga-eval/benchmarks/automationbench'))
sys.path.insert(0, os.path.expanduser('~/dev/polisys/src'))
import ab_env
from polisys.ruleset import is_write_tool
from pydantic import BaseModel
feat = json.load(open(os.path.expanduser('~/dev/cuga-eval/benchmarks/automationbench/results/policy_features.json')))
cnt = collections.Counter(); noarg = {}
for f in feat:
    t = ab_env.load_task(f['task']); w,_,_ = ab_env.build_world(t['info'])
    fns = ab_env.toolset_functions('full', t['info'])
    for a, v in w:
        if a == 'meta' or not isinstance(v, BaseModel): continue
        d = v.model_dump()
        if any(isinstance(x, (list, dict)) and x for k, x in d.items() if k != 'actions'): cnt[a] += 1
    for fn in fns:
        a = ab_env.tool_app(fn)
        if a in noarg or is_write_tool(fn.__name__): continue
        ps = [p for n, p in inspect.signature(fn).parameters.items() if n != 'world' and p.kind not in (p.VAR_KEYWORD, p.VAR_POSITIONAL)]
        if all(p.default is not p.empty for p in ps): noarg.setdefault(a, fn.__name__)
print('apps with data across', len(feat), 'tasks:')
for a, n in cnt.most_common(): print(f'  {a:20s} {n:4d}  no-arg read tool: {noarg.get(a)}')
