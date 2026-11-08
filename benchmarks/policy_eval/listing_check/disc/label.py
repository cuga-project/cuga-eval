"""Gold labels: which records state rules for the work. Reads the request and the records only (no grader, no checks).
usage: label.py <model> <outdir> [tasks...]"""
import sys, os, json, glob, concurrent.futures as cf, time
from openai import OpenAI
model, outdir = sys.argv[1], sys.argv[2]
client = OpenAI(base_url=os.environ['OPENAI_BASE_URL'], api_key=os.environ['OPENAI_API_KEY'], timeout=300)
SYSTEM = "You label business records for a policy audit. Output JSON only."
USER = """A worker gets this request:
<request>
{request}
</request>

Below are all records in the company's apps (email, chat, spreadsheets, CRM, helpdesk, ...), numbered.
Label a record RULE when it states how work must be done or decided, for this request or for work like it: a policy,
procedure, SOP, checklist, criteria, threshold, limit, exception, approval or sign-off requirement, routing or
assignment rule, deadline rule, a required template or format, or a change to such a rule (an update, a correction,
a rule that replaces or cancels another, or a rule marked old or no longer valid; keep these too). A worksheet whose
rows define rules (for example a table of thresholds, tiers or routing targets) is RULE.
Label everything else DATA: records the work acts on or reports facts (customers, tickets, invoices, rows to
process, chat that only asks or informs), and files unrelated to the work.
When unsure, choose RULE.

For each RULE record give a short quote (at most 15 words) copied exactly from the record that shows the rule.
Return {{"rule": [{{"n": <record number>, "quote": "..."}}]}}

Records:
{records}"""
def fmt(recs):
    return "\n\n".join(f"[{r['n']}] ({r['app']}) {json.dumps(r['record'], default=str)[:12000]}" for r in recs)
def one(path):
    d = json.load(open(path)); out = f"{outdir}/{d['task']}.json"
    if os.path.exists(out): return d['task'], 'cached'
    for attempt in range(4):
        try:
            r = client.chat.completions.create(model=model, messages=[{"role": "system", "content": SYSTEM},
                {"role": "user", "content": USER.format(request=d['request'], records=fmt(d['records']))}], max_tokens=8000)
            txt = r.choices[0].message.content
            j = json.loads(txt[txt.find('{'):txt.rfind('}') + 1])
            u = r.usage
            json.dump({'task': d['task'], 'rule': j.get('rule', []), 'usage': [u.prompt_tokens, u.completion_tokens]}, open(out, 'w'))
            return d['task'], len(j.get('rule', []))
        except Exception as e:
            err = str(e)[:200]; time.sleep(5 * (attempt + 1))
    return d['task'], 'ERR ' + err
paths = sorted(glob.glob('/tmp/aud/disc/records/*.json'))
if len(sys.argv) > 3: paths = [p for p in paths if os.path.basename(p)[:-5] in sys.argv[3:]]
with cf.ThreadPoolExecutor(6) as ex:
    for t, n in ex.map(one, paths): print(t, n, flush=True)
