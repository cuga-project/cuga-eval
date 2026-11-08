"""Candidate classifiers over ALL listed records. usage: classify.py gptoss|kev"""
import sys, os, json, glob, time, concurrent.futures as cf
which = sys.argv[1]
recs_by_task = {json.load(open(p))['task']: json.load(open(p)) for p in sorted(glob.glob('/tmp/aud/disc/records/*.json'))}
out_path = f'/tmp/aud/disc/new_{which}.json'
res = json.load(open(out_path)) if os.path.exists(out_path) else {}
SYSTEM = "You sort business records for a policy check. Output JSON only."
USER = """Request: {request}

Records from the company's apps, numbered. For each record say:
- "rule": it states how work must be done or decided (policy, procedure, criteria, threshold, exception, approval,
  routing, deadline, required format), or it changes, replaces or cancels such a rule, or it gives handling
  instructions for itself (for example a note saying not to contact this customer). A worksheet of rules is "rule".
- "data": anything else (records to work on, facts, questions, unrelated files).
- "unsure": you cannot tell.

Return {{"labels": [{{"n": <number>, "label": "rule" | "data" | "unsure"}}]}} with one entry per record.

Records:
{records}"""
MAX_CHARS = 14000
def batches(recs):
    cur, size = [], 0
    for r in recs:
        t = f"[{r['n']}] ({r['app']}) {json.dumps(r['record'], default=str)[:6000]}"
        if cur and size + len(t) > MAX_CHARS:
            yield cur; cur, size = [], 0
        cur.append(t); size += len(t)
    if cur: yield cur
if which == 'gptoss':
    from openai import OpenAI
    client = OpenAI(base_url=os.environ['OPENAI_BASE_URL'], api_key=os.environ['OPENAI_API_KEY'], timeout=120)
    def call(req, texts):
        for a in range(4):
            try:
                r = client.chat.completions.create(model='aws/gpt-oss-120b', max_tokens=16000, messages=[
                    {"role": "system", "content": SYSTEM}, {"role": "user", "content": USER.format(request=req[:3000], records="\n\n".join(texts))}])
                txt = r.choices[0].message.content or ''
                j = json.loads(txt[txt.find('{'):txt.rfind('}') + 1])
                return {int(x['n']): x['label'] for x in j.get('labels', [])}, [r.usage.prompt_tokens, r.usage.completion_tokens]
            except Exception as e:
                time.sleep(4 * (a + 1)); err = e
        return {}, [0, 0]
    def task(t):
        d = recs_by_task[t]; t0 = time.time()
        with cf.ThreadPoolExecutor(8) as ex:
            parts = list(ex.map(lambda b: call(d['request'], b), list(batches(d['records']))))
        labels = {}; use = [0, 0]
        for l, u in parts: labels.update(l); use = [use[0] + u[0], use[1] + u[1]]
        return t, {'labels': {str(k): v for k, v in labels.items()}, 'usage': use, 'secs': round(time.time() - t0, 1), 'calls': len(parts)}
else:
    sys.path.insert(0, os.path.expanduser('~/dev/cuga_snapshots/polisys-db0a72c/src'))
    from polisys.detectors import systemone_detector
    det = systemone_detector()
    def task(t):
        d = recs_by_task[t]; t0 = time.time()
        texts = [json.dumps(r['record'], default=str)[:6000] for r in d['records']]
        p = det(d['request'], texts)
        return t, {'p': {str(r['n']): s for r, s in zip(d['records'], p)}, 'secs': round(time.time() - t0, 1)}
todo = [t for t in recs_by_task if t not in res]
with cf.ThreadPoolExecutor(4) as ex:
    for t, v in ex.map(task, todo):
        res[t] = v; json.dump(res, open(out_path, 'w')); print(t, v.get('secs'), v.get('usage', ''), flush=True)
