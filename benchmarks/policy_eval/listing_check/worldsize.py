import sys, os, json, time
sys.path.insert(1, os.path.expanduser('~/dev/cuga-eval/benchmarks/automationbench'))
import ab_env
from pydantic import BaseModel
ids = [x['task'] for x in json.load(open(os.path.expanduser('~/dev/cuga-eval/benchmarks/automationbench/policy_types_fresh3.json')))['tasks']]
print('tasks', len(ids))
out = []
for tid in ids:
    t = ab_env.load_task(tid)
    w, info, init = ab_env.build_world(t['info'])
    per = {}
    t0 = time.perf_counter()
    for app, val in w:
        if not isinstance(val, BaseModel): continue
        d = val.model_dump(mode='json')
        s = json.dumps(d, default=str)
        n = 0
        for k, v in d.items():
            if isinstance(v, list): n += len(v)
            elif isinstance(v, dict): n += len(v)
        if n: per[app] = (n, len(s))
    dt = time.perf_counter() - t0
    out.append({'task': tid, 'apps': per, 'chars': sum(c for _, c in per.values()), 'records': sum(n for n, _ in per.values()), 'dump_s': dt})
json.dump(out, open('/tmp/aud/worldsize.json', 'w'))
import statistics as st
ch = [o['chars'] for o in out]; rc = [o['records'] for o in out]; ap = [len(o['apps']) for o in out]; ds = [o['dump_s'] for o in out]
print('apps with data: median', st.median(ap), 'max', max(ap))
print('records: median', st.median(rc), 'max', max(rc))
print('chars: median', st.median(ch), 'max', max(ch), '-> tokens ~', st.median(ch)//4, max(ch)//4)
print('dump time s: median %.4f max %.4f' % (st.median(ds), max(ds)))
