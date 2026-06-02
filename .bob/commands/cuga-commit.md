1. Commit current changes, one per file or (depends what user asks), but if its build files then all build files one commit

2. start by git status, and selectivly stage files for commit

3. follow https://www.conventionalcommits.org with scoping and for each commit add some bullet points in descrption

4. Pre-commit runs on commit (ruff on staged Python, detect-secrets); commit-msg hook enforces Conventional Commits. Run `just format` before committing if you changed Python.
