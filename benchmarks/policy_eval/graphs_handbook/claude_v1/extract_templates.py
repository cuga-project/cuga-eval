"""Exact email templates from an SOP converted to text: '## Template N – Name' up to the next heading."""

import json
import re
import sys

text = open(sys.argv[1]).read().split("\n")
out, cur = {}, None
for line in text:
    m = re.match(r"^## Template (\d+)\s*[–—:-]\s*(.+)$", line)
    if m:
        cur = m.group(1)
        out[cur] = {"number": int(cur), "name": m.group(2).strip(), "lines": []}
        continue
    if line.startswith("#"):
        cur = None
        continue
    if cur:
        out[cur]["lines"].append(line)
for k, t in out.items():
    body = "\n".join(t.pop("lines")).replace("- \n", "- ").strip()
    t["text"] = body
    t["slots"] = sorted(set(re.findall(r"\[[^\]]+\]", body)))
json.dump(out, open(sys.argv[2], "w"), indent=1, ensure_ascii=False)
print(len(out), "templates")
