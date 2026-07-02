Push one or more files into the cuga-wiki docs folder and show the live URL when done.

## Wiki repo
`~/dev/cuga-wiki` — remote: `github.ibm.com/research-rpa/cuga-wiki`, branch `main`, docs live in `docs/`.

## Steps

1. **Identify files to push**
   - If the user named specific files, use those.
   - Otherwise use the file(s) currently open or recently created in this session.
   - If still unclear, ask the user which file(s) to publish.

2. **Pull latest wiki main**
   ```bash
   cd ~/dev/cuga-wiki && git pull origin main
   ```

3. **Copy file(s) into docs/**
   ```bash
   cp <source-path> ~/dev/cuga-wiki/docs/<filename>
   ```
   Preserve the original filename unless the user asks for a different name.

4. **Stage and commit**
   ```bash
   cd ~/dev/cuga-wiki
   git add docs/<filename>
   git commit -m "docs: add <filename>"
   ```
   Use conventional commit style (`docs: <short description>`).

5. **Push to origin**
   ```bash
   git push origin main
   ```

6. **Show the links**
   After a successful push, print both the repo link and the live Pages URL:
   ```
   ✓ Repo:  https://github.ibm.com/research-rpa/cuga-wiki/tree/main/docs/<path>
   ✓ Pages: https://pages.github.ibm.com/research-rpa/cuga-wiki/<path>
   ```
   The Pages base is `https://pages.github.ibm.com/research-rpa/cuga-wiki/` (serves from `/docs` on `main`).
   Strip the leading `docs/` from the file path to form the Pages URL.
   If multiple files were pushed, list both URLs per file.
