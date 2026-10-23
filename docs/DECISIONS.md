# Decisions log

This file records significant architecture and ML decisions, the alternatives considered, and
their consequences. Entries are never deleted. A superseded decision is marked as such and
links to the entry that replaces it.

---

## D001 — Instruction precedence and spec conflicts
- **Date:** 2026-10-23 · **Task:** T001 · **Status:** Accepted
- **Context:** three requirement sources exist:
  - the owner's master build instructions, given to Claude Code and condensed in `CLAUDE.md`
  - [specs/CLAUDE_CODE_PROMPT.md](specs/CLAUDE_CODE_PROMPT.md)
  - [specs/DATASET_CATALOG.md](specs/DATASET_CATALOG.md)

  They mostly agree but conflict in places.
- **Decision:** the master build instructions govern the *workflow* and win any conflict. The
  two spec files remain the detailed product and dataset requirements. The known conflicts are
  resolved as follows:

  | Topic | CLAUDE_CODE_PROMPT.md | Master instructions | Resolution |
  |---|---|---|---|
  | Planning file | `IMPLEMENTATION_PLAN.md` | `docs/ROADMAP.md` and related records | `docs/ROADMAP.md`; no `IMPLEMENTATION_PLAN.md` |
  | Pace | Continue without waiting | One task per run, then stop | One task per run, then stop |
  | Chart library | Recharts or ECharts | Plotly or another suitable library | Open; decided in T030 against the actual chart needs |
  | Feedback labels | confirmed waste / expected behaviour / sensor or data fault / needs investigation | useful / incorrect / needs investigation | Open; decided in T025 |
- **Consequences:** future sessions read `CLAUDE.md` and `docs/PROJECT_STATUS.md` first. The
  open items are tracked in the roadmap tasks named above.

## D002 — Monorepo layout
- **Date:** 2026-10-23 · **Task:** T001 (applied in T002) · **Status:** Accepted
- **Decision:**
  - `backend/` is a single Python project with a **src-layout package `wattwise`**. Subpackages
    are added only when needed: `wattwise.api` (HTTP layer), `wattwise.core` (configuration and
    shared utilities), and later `wattwise.data` (contracts, ingestion, validation) and
    `wattwise.ml` (features, models, evaluation).
  - Dependency rule: `wattwise.ml` and `wattwise.data` must never import `wattwise.api`. The ML
    code stays usable from CLIs and notebooks without the web server.
  - `frontend/` holds the React app.
  - `scripts/` holds thin CLI entry points that call into `wattwise`.
  - `data/sample/` and `data/manifests/` are committed. `data/raw/` and `data/processed/` are git-ignored.
  - `artifacts/` (models, reports) is git-ignored.
- **Alternatives considered:**
  - A separate top-level `ml/` Python package. This gives stronger isolation, but means two
    projects, two environments and cross-package installs for every change. Revisit if the ML
    code ever needs an independent release.
  - A flat `backend/app/` package, the common FastAPI template. The generic name `app` makes CLI
    imports (`python -m app.ml.train`) unclear, and the flat layout allows accidental imports
    from the working directory.
- **Consequences:** one virtual environment and one test suite for all Python code. The
  dependency rule may be enforced by a test later if violations appear.

## D003 — Python tooling
- **Date:** 2026-10-23 · **Task:** T002 · **Status:** Accepted
- **Decision:**
  - Python `>=3.12`, developed on 3.13.
  - Standard `venv` + `pip`, with `pyproject.toml` built by hatchling. Dependencies use
    compatible-release bounds.
  - **ruff** for linting and formatting, **mypy --strict** with the pydantic plugin, **pytest**.
- **Alternatives considered:**
  - **uv:** faster, with a native lockfile. It is not installed on the development machine, and
    adding it now is not yet justified.
  - **Poetry:** heavier, and adds little at this scale.
- **Consequences:** installs are not fully locked yet. T004 (CI) decides the lock strategy,
  e.g. a compiled requirements lock or adopting uv, so CI and Docker builds are reproducible.

## D004 — Liveness vs readiness endpoints
- **Date:** 2026-10-23 · **Task:** T002 · **Status:** Accepted
- **Decision:** `GET /api/v1/health` is a liveness check only: the process is up, and it returns
  the service name, version and environment. `GET /api/v1/ready` is added in T023, when there is
  a real dependency (the database) to check.
- **Alternative considered:** a stub `/ready` that always returns OK. Rejected, because it would
  report readiness that was never checked.

## D005 — Primary dataset: Building Data Genome Project 2
- **Date:** 2026-10-23 · **Task:** T001 · **Status:** Accepted (licence verification pending in T007)
- **Decision:** BDG2 electricity meters are the primary training and evaluation data. They are
  hourly, non-residential data covering about 1,636 buildings in 2016–2017. Other datasets are
  used only for separate, clearly stated research questions and are never pooled with BDG2.
  A deterministic synthetic fixture (T006) runs the tests and the demo mode.
- **Caveats:**
  - Licence discrepancy: the Open Energy Data portal lists CC BY 4.0, while the GitHub
    repository's `LICENSE` shows CC BY-SA 4.0. T007 records the exact source used and resolves
    the applicable terms before any adapted data is shared.
  - The ASHRAE Great Energy Predictor III data overlaps BDG2. It is not independent external
    validation unless the overlap is checked.
  - Raw data is never committed. Downloading is an explicit, documented command.
- **Citation:** Miller, C. et al. (2020), *The Building Data Genome Project 2, energy meter
  data from the ASHRAE Great Energy Predictor III competition*. Scientific Data 7, 368.
  <https://doi.org/10.1038/s41597-020-00712-x>

---

## Open decisions (tracked in tasks)

| Topic | Decide in | Notes |
|---|---|---|
| Dependency lock strategy | T004 | Compiled lock vs uv; must make CI and Docker reproducible |
| Test database strategy | T023 | PostgreSQL service container in CI; the local option depends on Docker availability |
| Feedback label set | T025 | See D001 |
| Chart library | T030 | See D001; needs interval bands, synchronised zoom and accessibility |
| Browser E2E tooling | T035 | Only if justified |
