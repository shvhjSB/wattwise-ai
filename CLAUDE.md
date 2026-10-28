# WattWise AI — Working agreement for Claude Code

This file is loaded automatically in every session. It condenses the owner's build instructions.
Product and dataset requirements live in `docs/specs/`; the task plan lives in `docs/ROADMAP.md`.

## Start of every session

1. Read `docs/PROJECT_STATUS.md` (current task, blockers, next task).
2. Confirm the branch, remote and `git status`. Preserve any uncommitted user changes.
3. Work on **one** incomplete roadmap task only. When the owner says "Continue with the next
   task", pick the next incomplete task from `docs/PROJECT_STATUS.md`.

## Task loop (mandatory, one task per run)

1. Stay within the task's agreed scope. Split a task in the roadmap first if it is too large.
2. Run every available check: tests, lint, format, type check, build.
3. Review the diff for secrets, large files and unrelated changes.
4. Update `docs/ROADMAP.md`, `docs/PROJECT_STATUS.md`, `docs/WORK_LOG.md` and `CHANGELOG.md`.
   Add entries to `docs/DECISIONS.md` for significant choices.
5. Stage the task's files explicitly. Never `git add .` or `git add -A`.
6. Write a Conventional Commit, e.g. `feat(ml): add baseline energy forecasting`. Add **no**
   `Co-Authored-By` or other attribution trailers to commits or PR descriptions (owner's rule).
7. Push to `origin` on the current branch. Verify with `git ls-remote origin <branch>`.
8. Deliver the end-of-task report, then **stop** and wait for the owner.

The end-of-task report has these sections: Task completed, Files changed, Validation,
GitHub checkpoint, Project status, Next task, Decisions needed. Use plain language.

## Never

- `git push --force`, amending or rewriting published commits, or destructive reset/clean.
- Commit secrets, `.env` files, raw or processed datasets, local databases or large model artifacts.
- Commit unrelated pre-existing user changes.
- Claim a test, build or push succeeded without running it and seeing the result.
- Mark a task complete just because files exist.

## Scientific honesty rules

- Never fabricate metrics, costs, savings, carbon factors, weather or building metadata.
- Clearly label synthetic, inferred and observed data. Synthetic benchmark results are not
  real-world performance.
- An anomaly is not confirmed waste. Potential savings are not verified savings.
- Feature attributions (e.g. SHAP) are not causes. Phrase causes as hypotheses to investigate.
- Show cost only with an explicitly configured tariff, and carbon only with a sourced factor.
- Time-series splits are chronological; test windows are strictly later than training windows.
- Do not retrain production models on unreviewed feedback.

## Environment notes

- Windows development machine with Docker Desktop and PostgreSQL 18 installed (2026-10-23).
  PostgreSQL runs as the `postgresql-x64-18` service on `localhost:5432`, accepting local
  connections only. The superuser credentials live in the owner's libpq password file
  (`%APPDATA%\postgresql\pgpass.conf`). Never read, print or copy that file. The project role
  `wattwise` owns the databases `wattwise` and `wattwise_test` (created in T023); its URLs are in
  the git-ignored `backend/.env` (`uv run --env-file .env ...`). Never print that file either.
- Python work uses `backend/.venv`, managed by uv (0.12.24 or a later 0.12.x) from `backend/uv.lock`
  (`uv sync --locked`, `uv run --locked ...`). Never use the global interpreter. Change
  dependencies only with `uv add` / `uv lock`, and commit `uv.lock` together with `pyproject.toml`.
- **All commits and pushes for this project must be made as the owner's personal account,
  `shvhjSB`, and no other account** (see D006). This repo's local `.git/config` pins
  `user.name`/`user.email` and a credential helper that always authenticates as `shvhjSB`.
  Before committing, check `git config user.name` = `shvhjSB`. After pushing, the commit should be
  attributed to `shvhjSB` on GitHub. Never switch the global `gh` account, change remotes or alter
  credentials. If a push fails, report the exact error and the command the owner can run.
