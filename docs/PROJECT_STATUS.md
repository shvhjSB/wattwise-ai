# Project status

**Last updated:** 2026-10-23 · **Current milestone:** M1 — Repository audit and application foundation

## Summary

The repository audit is complete, and the project records and repo hygiene are in place. There
is no application code yet. No dataset has been downloaded and no model has been trained, so
no metrics exist.

## Completed tasks

| ID | Title | Completed |
|---|---|---|
| T001 | Repository audit, project records and hygiene | 2026-10-23 |

## Current task

None. Waiting for the owner to continue.

## Next task

**T002 — Backend foundation**: a FastAPI app factory, environment-based settings, a
`GET /api/v1/health` liveness endpoint, and pytest/ruff/mypy tooling. See [ROADMAP.md](ROADMAP.md#t002--backend-foundation).

## Milestone progress

| Milestone | Tasks | Done |
|---|---|---|
| M1 Foundation | T001–T004 | 1 / 4 |
| M2 Data contracts and acquisition | T005–T007 | 0 / 3 |
| M3 Validation and preprocessing | T008–T010 | 0 / 3 |
| M4 Baselines | T011–T012 | 0 / 2 |
| M5 Improved model | T013–T015 | 0 / 3 |
| M6 Anomaly detection | T016–T018 | 0 / 3 |
| M7 Explainability and uncertainty | T019–T020 | 0 / 2 |
| M8 Business impact | T021–T022 | 0 / 2 |
| M9 API and persistence | T023–T027 | 0 / 5 |
| M10 Frontend workflows | T028–T033 | 0 / 6 |
| M11 Integration | T034–T035 | 0 / 2 |
| M12 Operations and docs | T036–T039 | 0 / 4 |

## Blockers

- **GitHub push is blocked by authentication.** Local commits are safe and unpushed until the
  owner picks a push identity (see the first row of Known risks). This does not block local work.

## Known risks (from the T001 audit)

| Risk | Affects | Mitigation |
|---|---|---|
| Docker and PostgreSQL are not installed locally | T023, T034, T036 | Verify in GitHub Actions, or install Docker Desktop |
| `shvhjSB`'s `gh` token lacks the `workflow` scope | T004 | If the workflow push is rejected, the owner runs `gh auth refresh -h github.com -s workflow` as `shvhjSB`, or re-authenticates Git Credential Manager |
| **Push blocked (observed 2026-10-23):** git uses `gh auth git-credential` for github.com, which returns the *active* `gh` account (`aman-agntworksai`). That account has only READ access to `shvhjSB/wattwise-ai`, so `git push` fails with HTTP 403 | Every push | The owner chooses the push identity: switch the active `gh` account to `shvhjSB` (admin on the repo), or grant `aman-agntworksai` write access. Claude never changes accounts, remotes or credentials on its own |
| The repository is public | Every commit | Diff review before every commit. No secrets or data |
| BDG2 licence discrepancy (CC BY 4.0 vs CC BY-SA 4.0) | T007, T009 | Resolve and document in T007 before using the data |
| Global Python has unrelated packages installed (pandas 3, numpy 2.5) | All Python tasks | Always use `backend/.venv` |
