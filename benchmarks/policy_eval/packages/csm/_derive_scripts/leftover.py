"""Flag draft strings that still carry words of a changed statement's old text (n-grams not in the new text)."""
import json, re, sys
sys.path.insert(0, "/tmp/csm_work")
from align import stmts, align, ROOT, FAM

def grams(t, n=3):
    w = re.findall(r"[\w’'<>]+", t)
    return {" ".join(w[i:i + n]) for i in range(len(w) - n + 1)}

def walk(o, path=""):
    if isinstance(o, dict):
        for k, v in o.items():
            yield from walk(v, f"{path}.{k}")
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from walk(v, f"{path}[{i}]")
    elif isinstance(o, str):
        yield path, o

v = sys.argv[1]
b, n = stmts(ROOT / FAM[v] / "set.json"), stmts(ROOT / "derived" / v / "set.json")
_, changed, removed, _ = align(b, n)
f = sys.argv[2] if len(sys.argv) > 2 else "draft.json"
d = json.loads((ROOT / "derived" / v / f).read_text())
for o, nw, _ in changed + [(r, (None, ""), 0) for r in removed]:
    bad = grams(o[1]) - grams(nw[1])
    for path, s in walk(d):
        hit = [g for g in bad if g in " ".join(re.findall(r"[\w’'<>]+", s))]
        if hit:
            print(f"{v} {o[0]}: {path}: {s[:150]!r}  <- {hit[:2]}")
