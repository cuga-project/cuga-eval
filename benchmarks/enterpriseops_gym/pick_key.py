"""Print the LiteLLM key from cuga-eval/.env whose sha256 starts with the given prefix (also commented lines).
Use only in command substitution, never echo it:  export OPENAI_API_KEY=$(python3 -I pick_key.py 034bb8)"""

import hashlib
import re
import sys
from pathlib import Path

env = Path(__file__).resolve().parents[2] / ".env"
for m in re.finditer(r"^\s*#?\s*OPENAI_API_KEY\s*=\s*['\"]?([^'\"\s#]+)", env.read_text(), re.M):
    if hashlib.sha256(m.group(1).encode()).hexdigest().startswith(sys.argv[1]):
        print(m.group(1))
        break
else:
    sys.exit("key not found")
