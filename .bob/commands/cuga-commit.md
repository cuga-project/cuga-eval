1. Commit current changes, one per file or (depending on what the user asks), but if they are build files then include all build files in one commit.

2. Start by running `git status`, and selectively stage files for commit.

3. Follow https://www.conventionalcommits.org with scoping and for each commit add some bullet points in description.

4. Pre-commit runs on commit (ruff on staged Python, detect-secrets); commit-msg hook enforces Conventional Commits. Run `just format` before committing if you changed Python.
