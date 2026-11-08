import json, glob, statistics as st
gold = {json.load(open(f))['task']: {x['n'] for x in json.load(open(f))['rule']} for f in glob.glob('/tmp/aud/disc/gold/*.json')}
recs = {json.load(open(p))['task']: json.load(open(p)) for p in glob.glob('/tmp/aud/disc/records/*.json')}
old = json.load(open('/tmp/aud/disc/old.json')); kev = json.load(open('/tmp/aud/disc/new_kev.json')); gpt = json.load(open('/tmp/aud/disc/new_gptoss.json'))
def text80(r):
    def s(o):
        if isinstance(o, dict): return any(s(v) for v in o.values())
        if isinstance(o, list): return any(s(v) for v in o)
        return isinstance(o, str) and len(o) >= 80
    return s(r)
methods = {}
for t, g in gold.items():
    d = recs[t]; allr = {r['n'] for r in d['records']}; t80 = {r['n'] for r in d['records'] if text80(r['record'])}
    kp = {int(k): v for k, v in kev[t]['p'].items()}
    reached = set(old[t]['reached']); tier0 = set(old[t]['tier0_all'])
    gl = {int(k): v for k, v in gpt.get(t, {}).get('labels', {}).items()}
    sel = {
        'A. today: keyword searches, then words or Kev': {n for n in reached if n in tier0 or (n in t80 and kp.get(n, 0) >= 0.47)},
        'A0. today: records the searches return': reached,
        'B. list all + policy words only': tier0,
        'C. list all + Kev (today\'s detector)': {n for n in allr if n in tier0 or (n in t80 and kp.get(n, 0) >= 0.47)},
        'D. list all + gpt-oss (rule or unsure)': {n for n in allr if gl.get(n, 'unsure') != 'data'},
        'E. list all, send everything': allr,
    }
    for m, s in sel.items():
        methods.setdefault(m, []).append((len(g & s), len(g), len(s), t))
print(f"{'method':48s} {'recall (macro over tasks w/ rules)':>12s} {'pooled':>9s} {'tasks all found':>16s} {'records sent':>13s}")
for m, rows in methods.items():
    withr = [r for r in rows if r[1]]
    macro = st.mean(h / g for h, g, _, _ in withr); pooled = sum(h for h, _, _, _ in rows) / sum(g for _, g, _, _ in rows)
    full = sum(h == g for h, g, _, _ in withr); sent = sum(s for _, _, s, _ in rows)
    print(f"{m:48s} {100*macro:11.1f}% {100*pooled:8.1f}% {full:9d}/{len(withr)} {sent:13d}")
missD = [(t, sorted(gold[t] - {n for n in {r['n'] for r in recs[t]['records']} if {int(k): v for k, v in gpt.get(t, {}).get('labels', {}).items()}.get(n, 'unsure') != 'data'})) for t in gold]
print('D misses:', [(t, m) for t, m in missD if m])
u = [v['usage'] for v in gpt.values()]; s = [v['secs'] for v in gpt.values()]
print('gpt-oss tokens in/out', sum(x[0] for x in u), sum(x[1] for x in u), '| secs median', st.median(s), 'max', max(s), '| kev secs median', st.median(v['secs'] for v in kev.values()))
