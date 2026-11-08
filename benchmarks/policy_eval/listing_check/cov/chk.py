import json,glob,collections,importlib.util
spec=importlib.util.spec_from_file_location('lst','/Users/samimarreed/dev/polisys/src/polisys/listing.py',submodule_search_locations=[])
R='/Users/samimarreed/dev/cuga-eval-policy/benchmarks/policy_eval/harness/results'
import sys,types
pkg=types.ModuleType('polisys'); pkg.__path__=['/Users/samimarreed/dev/polisys/src/polisys']; sys.modules['polisys']=pkg
llm=types.ModuleType('polisys.llm'); llm.parse_json=json.loads; sys.modules['polisys.llm']=llm
spec=importlib.util.spec_from_file_location('polisys.listing','/Users/samimarreed/dev/polisys/src/polisys/listing.py'); L=importlib.util.module_from_spec(spec); spec.loader.exec_module(L)
exp={}
for p in glob.glob('/tmp/aud/disc/records/*.json'):
    d=json.load(open(p)); by=collections.defaultdict(list)
    for r in d['records']: by[r['app']].append(r['record'])
    exp[d['task']]=len(L.flatten(by))
diff=collections.Counter(); same=0
for f in glob.glob(f'{R}/lx_L_*_t*/*.json'):
    d=json.load(open(f)); l=[v for v in d['verdicts'] if v.get('outcome')=='listing'][0]
    if l['records']==exp[d['task']]: same+=1
    else: diff[(d['task'],l['records'],exp[d['task']])]+=1
print('listing count = offline dump:',same,'of 210; differ:',dict(diff))
print(json.dumps(json.load(open(f'{R}/lx_L_gptoss_t1/finance.cash_sweep.json'))['score'])[:300])
