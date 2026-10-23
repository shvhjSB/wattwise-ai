# Project status

**Last updated:** 2026-10-23 · **Current milestone:** M1 — Repository audit and application foundation

## Summary

The repository foundation and a tested FastAPI backend skeleton are in place. The backend
serves a liveness endpoint (`GET /api/v1/health`) and OpenAPI docs, and passes pytest, ruff and
strict mypy. No dataset has been downloaded and no model has been trained, so no ML metrics
exist yet.

## Completed tasks

| ID | Title | Completed |
|---|---|---|
| T001 | Repository audit, project records and hygiene | 2026-10-23 |
| T002 | Backend foundation (FastAPI, settings, liveness, tooling) | 2026-10-23 |

## Current task

None. Waiting for the owner to continue.

## Next task

**T003 — Frontend foundation**:
- a Vite + React + TypeScript + Tailwind app shell
- a typed API client and a health page with loading and error states
- ESLint, `tsc`, Vitest, React Testing Library and a production build

See [ROADMAP.md](ROADMAP.md#t003--frontend-foundation).

## Milestone progress

| Milestone | Tasks | Done |
|---|---|---|
| M1 Foundation | T001–T004 | 2 / 4 |
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

None.

The earlier push blocker (HTTP 403 as `aman-agntworksai`) was resolved on 2026-10-23. On the
owner's instruction, this repo now authenticates and commits as `shvhjSB` through a
repository-local git configuration (D006).

## Known risks

| Risk | Affects | Mitigation |
|---|---|---|
| Docker and PostgreSQL are not installed locally | T023, T034, T036 | Verify in GitHub Actions, or install Docker Desktop |
| `shvhjSB`'s `gh` token lacks the `workflow` scope | T004 | If the workflow push is rejected, the owner runs `gh auth refresh -h github.com -s workflow` while `shvhjSB` is selected |
| The push identity is pinned only in this clone's `.git/config` | Every push from another clone | Repeat the D006 setup in any new clone. The commands are in WORK_LOG (T002) |
| The repository is public | Every commit | Diff review before every commit. No secrets or data |
| BDG2 licence discrepancy (CC BY 4.0 vs CC BY-SA 4.0) | T007, T009 | Resolve and document in T007 before using the data |
| Dependencies are bounded but not locked | Reproducible CI and Docker builds | Lock strategy decided in T004 (D003) |
