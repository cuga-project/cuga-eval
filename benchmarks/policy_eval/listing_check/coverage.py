import sys, os, json, re, collections
sys.path.insert(1, os.path.expanduser('~/dev/cuga-eval/benchmarks/automationbench'))
sys.path.insert(0, os.path.expanduser('~/dev/cuga_snapshots/polisys-db0a72c/src'))
import ab_env
from polisys.intake import discovery_tools
from pydantic import BaseModel
ids = [x['task'] for x in json.load(open(os.path.expanduser('~/dev/cuga-eval/benchmarks/automationbench/policy_types_fresh3.json')))['tasks']]
miss = collections.Counter(); have = collections.Counter(); tasks_missing = 0
for tid in ids:
    t = ab_env.load_task(tid)
    fns = ab_env.toolset_functions('full', t['info'])
    w, info, init = ab_env.build_world(t['info'])
    data_apps = {a for a, v in w if isinstance(v, BaseModel) and any(isinstance(x,(list,dict)) and x for x in v.model_dump().values()) and a != 'meta'}
    disc = discovery_tools(fns)
    disc_apps = {ab_env.tool_app(f) for f in fns if f.__name__ in disc}
    m = data_apps - disc_apps
    for a in data_apps: have[a] += 1
    for a in m: miss[a] += 1
    tasks_missing += bool(m)
print('discovery tools (example):', disc)
print('tasks with >=1 data app never searched by discovery:', tasks_missing, '/', len(ids))
print('app: tasks with data / never searched')
for a, n in have.most_common(): print(f'  {a}: {n} / {miss[a]}')
