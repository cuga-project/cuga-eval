"""Align base and derived statements by text; print changes; write a remapped draft (draft.remap.json)."""
import difflib, json, sys
from pathlib import Path

ROOT = Path("/tmp/csm_pkg")
FAM = json.loads((ROOT / "families.json").read_text())


def stmts(path):
    out = []
    for d in json.loads(Path(path).read_text())["documents"]:
        for sec in d["sections"]:
            for s in sec["statements"]:
                out.append((s["id"], s["text"], sec.get("id"), sec.get("title")))
    return out


def norm(t):
    return " ".join(t.replace("’", "'").split()).lower()


def align(base, new):
    bt, nt = [norm(s[1]) for s in base], [norm(s[1]) for s in new]
    sm = difflib.SequenceMatcher(None, bt, nt, autojunk=False)
    idmap, changed, removed, added = {}, [], [], []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            for k in range(i2 - i1):
                idmap[base[i1 + k][0]] = new[j1 + k][0]
                if base[i1 + k][1] != new[j1 + k][1]:
                    changed.append((base[i1 + k], new[j1 + k], 1.0))
            continue
        olds, news = list(range(i1, i2)), list(range(j1, j2))
        used = set()
        for i in olds:
            best, bj = 0, None
            for j in news:
                if j in used:
                    continue
                r = difflib.SequenceMatcher(None, bt[i], nt[j], autojunk=False).ratio()
                if r > best:
                    best, bj = r, j
            if len(olds) == len(news):
                bj, best = news[olds.index(i)], difflib.SequenceMatcher(None, bt[i], nt[news[olds.index(i)]]).ratio()
            if bj is not None and (best >= 0.6 or len(olds) == len(news)):
                used.add(bj)
                idmap[base[i][0]] = new[bj][0]
                changed.append((base[i], new[bj], best))
            else:
                removed.append(base[i])
        for j in news:
            if j not in used:
                added.append(new[j])
    return idmap, changed, removed, added


def remap(obj, m):
    if isinstance(obj, dict):
        return {m.get(k, k): remap(v, m) for k, v in obj.items()}
    if isinstance(obj, list):
        return [remap(v, m) for v in obj]
    if isinstance(obj, str) and obj in m:
        return m[obj]
    return obj


if __name__ == "__main__":
    v = sys.argv[1]
    base = FAM[v]
    b, n = stmts(ROOT / base / "set.json"), stmts(ROOT / "derived" / v / "set.json")
    idmap, changed, removed, added = align(b, n)
    moved = {k: x for k, x in idmap.items() if k != x}
    # section ids: map by statement section
    secmap = {}
    for s in b:
        if s[0] in idmap:
            ns = next(x for x in n if x[0] == idmap[s[0]])
            secmap.setdefault("policy:" + s[2], "policy:" + ns[2])
    secmoved = {k: x for k, x in secmap.items() if k != x}
    print(f"== {v} (base {base}) {len(b)} -> {len(n)} statements")
    print("moved ids:", moved)
    print("moved sections:", secmoved)
    bt = {x[2]: x[3] for x in b}; ntt = {x[2]: x[3] for x in n}
    for k, x in secmap.items():
        if bt.get(k[7:]) != ntt.get(x[7:]):
            print(f"SECTION TITLE {k} -> {x}: {bt.get(k[7:])!r} -> {ntt.get(x[7:])!r}")
    for o, nw, r in changed:
        print(f"CHANGED {o[0]} -> {nw[0]} ({r:.2f})\n  OLD: {o[1]}\n  NEW: {nw[1]}")
    for o in removed:
        print(f"REMOVED {o[0]}: {o[1]}")
    for a in added:
        print(f"ADDED {a[0]} [{a[3]}]: {a[1]}")
    if "--write" in sys.argv:
        draft = json.loads((ROOT / base / "draft.json").read_text())
        m = {**secmoved, **moved}
        out = remap(draft, m)
        # replace full old texts of changed statements by the new texts inside strings
        s = json.dumps(out, ensure_ascii=False)
        for o, nw, r in changed:
            if o[1] != nw[1]:
                s = s.replace(json.dumps(o[1], ensure_ascii=False)[1:-1], json.dumps(nw[1], ensure_ascii=False)[1:-1])
        (ROOT / "derived" / v / "draft.remap.json").write_text(json.dumps(json.loads(s), indent=1, ensure_ascii=False))
        print("wrote draft.remap.json")
