import json, sys
sys.path.insert(0, "/tmp/csm_work")
from align import stmts, ROOT, FAM, norm
for v in sorted(p.name for p in (ROOT / "derived").iterdir()):
    b = {s[0]: s[1] for s in stmts(ROOT / FAM[v] / "set.json")}
    n = {s[0]: s[1] for s in stmts(ROOT / "derived" / v / "set.json")}
    bm = {norm(b[k]): m for k, m in json.loads((ROOT / FAM[v] / "draft.json").read_text())["modality"].items()}
    nm = {norm(n[k]): (k, m) for k, m in json.loads((ROOT / "derived" / v / "draft.json").read_text())["modality"].items()}
    out = []
    for t, (k, m) in nm.items():
        if bm.get(t) != m:
            out.append(f"  {k}: {bm.get(t)} -> {m}: {t[:70]}")
    for t, m in bm.items():
        if t not in nm:
            out.append(f"  (gone) {m}: {t[:70]}")
    print(v, "\n".join([""] + out) if out else "same")
