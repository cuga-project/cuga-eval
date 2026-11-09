import sys,glob,json,statistics as st,random,math,importlib.util
spec=importlib.util.spec_from_file_location('n','/Users/samimarreed/dev/cuga-eval-policy/benchmarks/enterpriseops_gym/numeric_string_fix.py'); n=importlib.util.module_from_spec(spec); spec.loader.exec_module(n)
T=n.tasks(); R='/Users/samimarreed/dev/cuga-eval-policy/benchmarks/policy_eval/harness/results/'
def L(pres,fix):
    S={};P={}
    for pre in pres:
        for f in glob.glob(R+pre+'_t[0-9]/task_*.json'):
            d=json.load(open(f))
            if not d.get('score'): continue
            r=n.rescore(d,T[d['task']]) if fix else {'pass':d['score']['pass'],'partial':d['score']['partial']}
            S.setdefault(d['task'],[]).append(float(r['pass'])); P.setdefault(d['task'],[]).append(float(r['partial'] or 0))
    return S,P
def cmp(a,b,label,fix=True):
    A=L(a,fix); B=L(b,fix); out=[]
    for i,k in enumerate(('strict','partial')):
        ts=sorted(set(A[i])&set(B[i])); d=[st.mean(B[i][t])-st.mean(A[i][t]) for t in ts]; obs=st.mean(d); rng=random.Random(0)
        p=sum(st.mean(x*rng.choice((1,-1)) for x in d)>=obs for _ in range(10000))/10000
        se=math.sqrt(2*st.mean(st.pvariance(A[i][t]) for t in ts)/3/len(ts))
        out.append(f"{k} {100*st.mean(st.mean(A[i][t]) for t in ts):.1f}->{100*st.mean(st.mean(B[i][t]) for t in ts):.1f} ({100*obs:+.1f}, SE {100*se:.1f}, p {p:.3f}, noharm {'ok' if obs>=-2*se else 'FAIL'}) n={len(ts)} runs={sum(len(B[i][t]) for t in ts)}")
    print(f"{label:28s} {'fixed' if fix else 'upstream'}  "+' | '.join(out))
A=['hr_base_heldout']; K=['hr_rb_heldout']
cmp(A,K,'HR read-back vs alone'); cmp(A,K,'HR read-back vs alone',fix=False)
