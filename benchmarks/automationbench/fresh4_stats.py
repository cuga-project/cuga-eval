import json,glob,statistics as st,random,math
FL=json.load(open('/Users/samimarreed/dev/cuga-eval-policy/benchmarks/automationbench/upstream_flagged_checks_fresh4_2026-11-09.json'))
def key(c):
    p=c.get('params') if 'params' in c and isinstance(c.get('params'),dict) and c['type'] and set(c)-{'type','params','negative','guard'}==set() else {k:v for k,v in c.items() if k not in('type','negative','guard')}
    return c['type']+json.dumps(p,sort_keys=True)
FK={t:{key(c) for c in cs} for t,cs in FL.items()}
def load(arm):
    S,P,G,X={}, {}, {}, {}
    for t in (1,2,3):
        for f in glob.glob(f'{arm}_t{t}/*.json'):
            d=json.load(open(f)); s=d.get('score')
            if not s: continue
            k=d['task']; fl=s['detail'].get('failed',[])
            nf=all(key(c) in FK.get(k,set()) for c in fl) if fl else bool(s['pass'])
            S.setdefault(k,[]).append(float(s['pass'])); P.setdefault(k,[]).append(float(s['partial'] or 0))
            G.setdefault(k,[]).append(float(s['guardrails_broken'])); X.setdefault(k,[]).append(float(nf))
    return S,P,G,X
def test(A,B,higher_bad=False):
    ts=sorted(set(A)&set(B)); d=[st.mean(B[t])-st.mean(A[t]) for t in ts]; obs=st.mean(d); r=random.Random(0)
    p=sum(st.mean(x*r.choice((1,-1)) for x in d)>=obs for _ in range(10000))/10000
    bs=sorted(st.mean(r.choice(d) for _ in d) for _ in range(5000)); ci=(bs[124],bs[4874])
    se=math.sqrt(2*st.mean(st.pvariance(A[t]) for t in ts)/3/len(ts))
    ok=(obs<=2*se) if higher_bad else (obs>=-2*se)
    return st.mean(st.mean(A[t]) for t in ts),st.mean(st.mean(B[t]) for t in ts),obs,ci,p,se,ok,len(ts),sum(len(B[t]) for t in ts)
for a,b in [('f4_R_haiku55','f4_B_haiku55'),('f4_R_gptoss','f4_B_gptoss'),('f4_R_gptoss','f4_L_gptoss')]:
    A=load(a);B=load(b)
    for i,nm in enumerate(['strict','partial','guards','strict-noflag']):
        hb=nm=='guards'; m=1 if hb else 100
        x=test(A[i],B[i],hb)
        print(f"{b[3:]:12s} vs {a[3:]:12s} {nm:13s} {m*x[0]:6.2f} -> {m*x[1]:6.2f}  d {m*x[2]:+6.2f} CI [{m*x[3][0]:+.1f},{m*x[3][1]:+.1f}] p {x[4]:.3f} SE {m*x[5]:.2f} noharm {'ok' if x[6] else 'FAIL'} n={x[7]} runs={x[8]}")
