"""Live coverage: did the policies the layer extracted in each run state the gold rule records?
Gold: /tmp/aud/disc/gold (Opus 5.5 labels from the request and records only). Judge: a model, with quoted evidence;
code checks every cited statement number exists. usage: livecov.py <judge-model> <run-glob>..."""
import sys, os, json, glob, re, concurrent.futures as cf
from openai import OpenAI
judge, globs = sys.argv[1], sys.argv[2:]
cli = OpenAI(base_url=os.environ['OPENAI_BASE_URL'], api_key=os.environ['OPENAI_API_KEY'], timeout=300)
R = '/Users/samimarreed/dev/cuga-eval-policy/benchmarks/policy_eval/harness/results'
gold = {json.load(open(f))['task']: json.load(open(f))['rule'] for f in glob.glob('/tmp/aud/disc/gold/*.json')}
recs = {json.load(open(p))['task']: {r['n']: r for r in json.load(open(p))['records']} for p in glob.glob('/tmp/aud/disc/records/*.json')}
OUT = '/tmp/aud/cov/out'; os.makedirs(OUT, exist_ok=True)
SYS = "You audit a policy extraction. Output JSON only."
USR = """Rule records from a company's apps (each with a short quote that shows its rule):
{gold}

Statements a system extracted (numbered):
{stmts}

For each rule record, say whether the extracted statements state the rule shown by its quote: same condition and same
value or action (a paraphrase counts; a statement on the same topic with a different value or missing the condition
does not). Cite the statement numbers that state it.
Return {{"rules": [{{"n": <record number>, "covered": true|false, "statements": [<numbers>]}}]}}"""
norm = lambda s: re.sub(r'\s+', ' ', s.lower()).strip()
def stmts_of(d):
    out = []; first_write = None
    for i, v in enumerate(d['verdicts']):
        if first_write is None and v.get('hook') == 'before_tool_call': first_write = i
        if v.get('outcome') == 'policy_found':
            for s in v.get('statements') or []:
                out.append((i, f"[{v.get('title','')}] {s}"))
    return out, first_write
def one(f):
    run = f.split('/')[-2]; d = json.load(open(f)); t = d['task']
    key = f"{OUT}/{run}__{t}.json"
    if os.path.exists(key): return json.load(open(key))
    g = gold.get(t, []); st, fw = stmts_of(d)
    res = {'run': run, 'task': t, 'score': d.get('score'), 'n_stmts': len(st), 'rules': {}}
    if not g:
        json.dump(res, open(key, 'w')); return res
    todo = []
    for x in g:
        hit = [k for k, (_, s) in enumerate(st, 1) if norm(x['quote']) in norm(s)]
        if hit: res['rules'][x['n']] = {'covered': True, 'statements': hit, 'by': 'copied'}
        else: todo.append(x)
    for i in range(0, len(todo) if st else 0, 12):
        part = todo[i:i + 12]
        gt = "\n\n".join(f"[{x['n']}] quote: \"{x['quote']}\"\nrecord: {json.dumps(recs[t][x['n']]['record'], default=str)[:2500]}" for x in part)
        sl = "\n".join(f"{k}. {s}" for k, (_, s) in enumerate(st, 1))
        for a in range(4):
            try:
                r = cli.chat.completions.create(model=judge, max_tokens=4000, messages=[{"role": "system", "content": SYS},
                    {"role": "user", "content": USR.format(gold=gt, stmts=sl)}])
                txt = r.choices[0].message.content; j = json.loads(txt[txt.find('{'):txt.rfind('}') + 1])
                u = res.get('usage') or [0, 0]; res['usage'] = [u[0] + r.usage.prompt_tokens, u[1] + r.usage.completion_tokens]; break
            except Exception as e:
                j = None; err = str(e)[:200]
        for x in part:
            e = next((y for y in (j or {}).get('rules', []) if int(y.get('n', -1)) == x['n']), None)
            if e is None: res['rules'][x['n']] = {'covered': None, 'by': 'judge_missing'}; continue
            ok = [k for k in e.get('statements') or [] if isinstance(k, int) and 1 <= k <= len(st)]
            res['rules'][x['n']] = {'covered': bool(e.get('covered')) and bool(ok), 'statements': ok, 'by': 'judge'}
    for x in todo:
        res['rules'].setdefault(x['n'], {'covered': False, 'statements': [], 'by': 'no_statements'})
    for n, v in res['rules'].items():  # available before the first write?
        v['before_first_write'] = bool(v.get('covered')) and (fw is None or any(st[k - 1][0] < fw for k in v['statements']))
    json.dump(res, open(key, 'w')); return res
files = [f for gl in globs for f in glob.glob(f"{R}/{gl}/*.json")]
with cf.ThreadPoolExecutor(12) as ex:
    out = list(ex.map(one, files))
print(len(out), 'runs judged')
