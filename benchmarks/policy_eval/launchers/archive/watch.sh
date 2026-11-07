#!/bin/bash
# Print one line per finished task in results/$1; exit when run_all.sh or the proxy stops.
# Written for macOS /bin/bash 3.2 (no associative arrays).
cd "$(dirname "$0")"
D=results/${1:-cuga_glm53flash_api}
SEEN=$(mktemp)
shopt -s nullglob
for f in "$D"/*.json; do echo "$f" >> "$SEEN"; done
while true; do
  for f in "$D"/*.json; do
    grep -qxF "$f" "$SEEN" && continue
    echo "$f" >> "$SEEN"
    python3 -c "import json; r=json.load(open('$f')); print(('PASS' if r['pass'] else 'fail'), r['task'], 'pc=%.2f' % r['partial_credit'], '%ss' % r['wall_s'], (r.get('error') or '')[:120])"
  done
  if ! pgrep -f run_all.sh >/dev/null; then echo "run_all.sh exited"; tail -5 run_all.out; exit 0; fi
  if ! pgrep -f retry_proxy.py >/dev/null; then echo "retry_proxy.py is not running"; exit 1; fi
  sleep 30
done
