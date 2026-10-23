# Work log

Concise, chronological record of completed task checkpoints. A commit cannot contain its own
hash, so each entry's commit hash is recorded in the *next* checkpoint's entry (and always in
the end-of-task report).

---

## 2026-10-23 — T001 Repository audit, project records and hygiene

**Audit findings**
- **Commits:** the repository had one commit (`7711d9d`, "Initial commit") containing only `LICENSE` (MIT).
- **Untracked files:** two untracked user files, `CLAUDE_CODE_PROMPT.md` and `DATASET_CATALOG.md`,
  with no secrets. With the owner's approval they were moved unchanged to `docs/specs/` and committed.
- **Missing basics:** no `.gitignore`, README, code, tests or tooling.
- **Remote:** `origin` is `https://github.com/shvhjSB/wattwise-ai` (public). `main` is not protected.
  Git authenticates through `gh auth git-credential`, i.e. as the active `gh` account.
- **Toolchain:**
  - Available: Python 3.13, Node 24, npm 11, GitHub CLI.
  - Not installed: Docker, PostgreSQL, uv.

**Done**
- Added `.gitignore`, `.gitattributes`, `.editorconfig`, README, `CLAUDE.md` and CHANGELOG.
- Added the roadmap, status, decisions (D001–D005) and this work log.

**Validation:** `git check-ignore -v` confirmed that secrets, datasets, artifacts, local DBs,
virtualenvs and `node_modules` are ignored, and that `.env.example` and `data/sample/` are not.

**Push attempt:** `git push origin main` for commit `034c2f9` failed with HTTP 403:
"Permission to shvhjSB/wattwise-ai.git denied to aman-agntworksai". The active `gh` account has
only READ access. The commit was preserved locally. The audit note claiming that pushes would
use Git Credential Manager as `shvhjSB` was wrong and has been corrected in a follow-up commit.
