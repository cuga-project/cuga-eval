"""Listing experiment: arms R, P, L (gpt-oss, fresh3). Pre-registered decision rule."""
import json, os, random, statistics as st, glob
R = os.path.expanduser('~/dev/cuga-eval-policy/benchmarks/policy_eval/harness/results/')
tasks = [x['task'] for x in json.load(open(os.path.expanduser('~/dev/cuga-eval-policy/benchmarks/automationbench/policy_types_fresh3.json')))['tasks']]
M = os.environ.get('LXM', 'gptoss')
def arm(name):
    out = {}
    for t in tasks:
        v = [json.load(open(f))['score'] for tr in (1, 2, 3) if os.path.exists(f := f'{R}{name}_t{tr}/{t}.json')]
        if v: out[t] = v
    return out
def val(s, k): return (1.0 if s.get('pass') else 0.0) if k == 'strict' else (s.get(k) or 0)
def m(v, k): return st.mean(val(s, k) for s in v)
def perm_p(d, n=20000):
    obs = abs(sum(d)); rnd = random.Random(0)
    return sum(abs(sum(x if rnd.random() < .5 else -x for x in d)) >= obs - 1e-12 for _ in range(n)) / n
def boot(d, n=10000):
    rnd = random.Random(1); xs = sorted(st.mean(rnd.choice(d) for _ in d) for _ in range(n)); return xs[int(.025*n)], xs[int(.975*n)]
A = {k: arm(f'lx_{k}_{M}') for k in 'RPL'}
print('runs:', {k: sum(len(v) for v in r.values()) for k, r in A.items()})
for k, r in A.items():
    if r: print(f'  {k}: tasks {len(r)} strict {100*st.mean(m(v,"strict") for v in r.values()):.1f} partial {100*st.mean(m(v,"partial") for v in r.values()):.1f} guards {st.mean(m(v,"guardrails_broken") for v in r.values()):.2f}')
full = {k: {t: v for t, v in r.items() if len(v) == 3} for k, r in A.items()}
n = len(full['R'])
se = {}
for k in ('strict', 'partial', 'guardrails_broken'):
    if n: se[k] = (2 * st.mean(st.variance([val(x, k) for x in v]) for v in full['R'].values()) / 3 / n) ** .5
for a, b in (('P', 'L'), ('R', 'L'), ('R', 'P')):
    common = [t for t in tasks if t in A[a] and t in A[b]]
    if not common: continue
    for k in ('strict', 'partial', 'guardrails_broken'):
        d = [m(A[b][t], k) - m(A[a][t], k) for t in common]; f = 1 if k == 'guardrails_broken' else 100
        lo, hi = boot(d)
        print(f'{b}-{a} {k:17s} n={len(common)} diff {st.mean(d)*f:+.2f} CI [{lo*f:+.1f},{hi*f:+.1f}] up {sum(x>1e-9 for x in d)} down {sum(x<-1e-9 for x in d)} p={perm_p(d):.3f} 2SE {2*se.get(k,0)*f:.2f}')
# mechanism
runs = glob.glob(f'{R}lx_L_{M}_t*/work/*/audit.jsonl'); hit = 0
for f in runs:
    hit += any(json.loads(l).get('verdict') == 'listing' for l in open(f))
print(f'mechanism: listing record in {hit}/{len(runs)} L runs')
