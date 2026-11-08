import json, glob, collections, statistics as st, sys
rows = [json.load(open(f)) for f in glob.glob('/tmp/aud/cov/out/*.json')]
arms = collections.defaultdict(list)
for r in rows: arms[r['run'].rsplit('_t', 1)[0]].append(r)
tok = [0, 0]
for r in rows:
    u = r.get('usage') or [0, 0]; tok[0] += u[0]; tok[1] += u[1]
print('judge tokens in/out', tok)
for a, rs in sorted(arms.items()):
    tot = cov = fw = miss_j = 0; per = []; allf = 0; withr = 0; by = collections.Counter()
    for r in rs:
        v = list(r['rules'].values())
        if not v: continue
        withr += 1; tot += len(v); c = sum(1 for x in v if x['covered']); cov += c
        fw += sum(1 for x in v if x['before_first_write']); miss_j += sum(1 for x in v if x['covered'] is None)
        per.append(c / len(v)); allf += c == len(v)
        for x in v: by[x['by'] + ('+' if x['covered'] else '-')] += 1
    print(f"{a:16s} runs {len(rs):3d} rule-records {tot:4d} covered {cov/tot:6.1%} (mean/task {st.mean(per):6.1%}) "
          f"before 1st write {fw/tot:6.1%} runs-all-covered {allf}/{withr} judge-missing {miss_j} {dict(by)}")
