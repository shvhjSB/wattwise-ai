# T051: current-state verification and gap analysis

**Date:** 2026-11-02 · **Commit audited:** `89512fe` (working tree clean) · **Milestone:** M13

This compares what the repository documents with what actually runs. Every item cites a file and
line, a test, a command result, or a CI run. Commands ran on the development machine (Windows 11,
15.3 GB RAM, PostgreSQL 18 locally, Docker Desktop) unless a CI run is named. Evidence files
from the commands were kept outside the repository.

**Environment note:** the machine had about 2 GB of free RAM during the audit (Docker Desktop's VM
alone commits 7.7 GB). The first model re-score and one backend test failed for that reason only;
both passed when rerun alone (below).

## Summary

| | Count | Most important |
|---|---|---|
| Verified working | 18 | The promoted model's test results **reproduce exactly**; CI, Pages, browser suites, provenance |
| Implemented but unverified | 5 | Render and the private Docker host never ran on a real host; BDG2 data-quality audit never stored |
| Broken | 4 | **`/api/v1/models/drift` times out on the real BDG2 data** (74.7 s query, 60 s deadline) |
| Missing | 6 | **No authentication**; real-data public deployment; short-anomaly detection |
| Blocked by external services | 3 | Render needs a card; Hugging Face Docker needs a paid plan; BDG2/LEAD licences |

## Documented metrics: reproduced or not

| Metric (where documented) | Documented | T051 result | Evidence |
|---|---|---|---|
| Model test MAE, all scored rows (MODEL_CARD.md:69) | 13.720 kWh | **13.720335, reproduced exactly** (RMSE 76.699835, bias −0.544688, WAPE 0.088256, 2,283,087 rows: all identical to the artifact's metadata) | Re-score of CURRENT `20261027T121334Z-eeec81e9592c` on 2017-10-01 to 2018-01-02, no training, 119 s |
| Model vs seasonal-naive, common rows (MODEL_CARD.md:78) | 13.700 vs 16.705, −18.0 % | **13.700259 vs 16.705278 on 2,261,050 rows, −17.99 %: reproduced** | Same re-score |
| 90 % interval coverage on test (MODEL_CARD.md:87) | 87.2 % | **0.8723 stored** (`expectation_sets.measured_coverage`, dev DB); not recomputed | Dev DB query |
| Injected-anomaly recall, default detector (README, EVALUATION T044b) | 70.0 % at 0.341 alerts/meter-week | **0.6995 at 0.3414 in the stored report**; not re-run | `data/processed/fullscale-downstream/benchmark/benchmark.json` |
| Human-labelled segment recall (MODEL_CARD.md:95, EVALUATION.md:771) | 18.9 % | **0.1886 in the stored report** (1–2 h segments: 0.1304; 3–23 h: 0.319; ≥24 h: 0.364); not re-run | `data/processed/fullscale-downstream/lead-scale/lead_check.json` |
| HKUST generalisation (MODEL_CARD.md:101) | −6.6 % | **−0.0659 in the stored summary**; not re-run | `data/processed/hkust/evaluation/summary.json` |

All documented numbers agree with each other across README, MODEL_CARD, EVALUATION and DETECTION.

## Verified working

1. **Git and CI:** branch `main`, remote `shvhjSB/wattwise-ai`, clean tree at `89512fe`. CI run
   41421743043 passed all five jobs (backend, frontend, secret scan, containers and browser,
   public demo image); Pages run 41422287090 built and published.
2. **Model registry:** all four stored versions pass `registry.verify` (file hashes and metadata);
   CURRENT is `20261027T121334Z-eeec81e9592c`, LightGBM, 1,779 trees, trained 2016-01-11 to
   2017-06-30 on 3,112,661 rows from 1,146 meters (49 MB).
3. **Test-window results reproduce exactly** (table above).
4. **Backend static checks:** `uv lock --check`, ruff, ruff format (162 files) and strict mypy (161
   files) clean.
5. **Backend tests:** **1,002 of 1,002 passed** (466 s) when run alone. A first run, alongside
   the memory-starved re-score, had 1,001 passes and one setup error
   (`tests/api/test_catalog.py::test_the_summary_counts_what_is_stored`); that file then passed
   three times alone (32 tests each).
6. **Migrations:** the local dev database was at `0006`; `python -m wattwise.operations migrate`
   brought it to `0007` (`{"event": "migration_complete", "revision": "0007"}`); the migration
   tests compare models and migrations (`backend/tests/db/test_migrations.py`).
7. **API against real BDG2 data** (dev DB: 1,148 BDG2 meters, 20,137,056 readings, 5,546
   alerts): 21 of 22 GET calls answered 200 in 9–571 ms (health, ready, dashboard summary,
   buildings with and without search, building, meters, meter, series, expectation, alerts list,
   filtered and detail, impact with and without a tariff, model metadata, metrics and evaluation,
   analysis runs, data quality). The exception is drift (Broken, 1).
8. **Write endpoints:** without read-only mode they validate input (422 for a bad label or a
   missing file); with `WATTWISE_READ_ONLY=true` all three answer 403 with the plain reason.
9. **Frontend:** typecheck, lint (40 s), format and build pass with exit code 0; Vitest 293 of 293
   in three consecutive full runs (the one alerts-page failure seen during T050 did not recur).
10. **Browser suite:** 18 of 18 scenarios (6 workflows on desktop light, dark and mobile) against a
    real API and database (`node scripts/e2e.mjs`).
11. **Public static demo:** <https://shvhjsb.github.io/wattwise-ai/> serves over HTTPS
    (`https_enforced: true`, `build_type: workflow`); 92 recorded answers; health says
    `read_only: true`; all 7 pages load with data and no page errors in a browser; building search
    shows the documented "not part of the static demo" message; the review form is replaced by the
    read-only notice.
12. **Render image** (`bash deploy/render/verify.sh`, 0.1 CPU, 512 MB): first start with seeding
    110 s, restart without reseeding 72 s, 176 MiB; PASS. Also passes in CI on every push.
13. **Synthetic data-quality backfill:** `python -m wattwise.db.quality --dataset-id
    synthetic-sample` on the dev DB: 4 meters, 5,376 rows, coverage 99.89 %, 1 meter with
    warnings, 5 s.
14. **Provenance:** recomputed SHA-256 of every raw file matches its manifest: BDG2 (4 files),
    LEAD (1), LBNL Building 59 (4), HKUST (2), HKUST ERA5 (1), and the 15 BDG2 ERA5 site
    responses (`data/raw/era5/manifest.json`, kept out of git on purpose because it holds site
    coordinates: DATASETS.md:595).
15. **No data in git:** only manifests, the two cited reference tables and the synthetic sample
    are tracked under `data/` (`git ls-files data/`).
16. **Security controls present:** request size, deadline and concurrency limits
    (`backend/src/wattwise/core/config.py:30-34`), explicit CORS allow-list (empty by default,
    `config.py:31`), read-only mode, security headers on the single-service image, CI
    dependency audits and full-history secret scan.
17. **Stored expectations:** 1,124 of 1,148 BDG2 meters have stored expectations; the 24 without
    match the documented open item.
18. **Documented numbers are consistent** across README, MODEL_CARD, EVALUATION, DETECTION and
    the HKUST report.

## Implemented but unverified

1. **Render deployment** (`render.yaml`, T046): the image passes under the free plan's limits,
   but the Blueprint was never applied (Render asks for a card).
2. **Private Docker-host recipe** (`deploy/compose.yaml`, T038): verified only by the CI verifier
   (`npm run test:deployment`), never on a real host.
3. **BDG2 data-quality audit:** never stored. The backfill (`backend/src/wattwise/db/quality.py:83`,
   `stored_tables`) loads every reading as a Python row; 1,000,000 BDG2 rows took 27.7 s and
   638 MiB (`tracemalloc`), about **12.5 GiB for all 20 million rows** before the checks run. Not
   run here; the API correctly answers "not audited yet" for `bdg2-cleaned-all`.
4. **Full-scale retraining** reproducibility (`python -m wattwise.ml.fullscale --evaluation-model`)
   was not rerun; only the promoted model was re-scored.
5. **Detector evaluations** (injected benchmark, LEAD check, HKUST) were read from stored reports,
   not re-run.

## Broken

1. **`GET /api/v1/models/drift` times out on real data.** On the dev DB it answered **504 after
   60,016 ms**; the query alone (`backend/src/wattwise/api/routes/drift.py`, `_PER_METER`) took
   **74.7 s** for 7,313 meter-months. T048 was tested only on the synthetic sample, and its
   docstring (`drift.py:3`, "so it scales to millions of rows") and D066 (DECISIONS.md:2253) claim
   more than was shown. Because a 504 does not cancel database work (SECURITY.md:26-31), repeated
   requests would stack 75-second queries on a server.
2. **Local Compose demo is stale:** containers from an image built 2026-11-01 answer 404 on
   `/models/drift` and `/datasets/{id}/quality`. Environment drift only: CI rebuilds and passes;
   `docker compose up --build -d` refreshes it.
3. **Doc defects (all four fixed in T051's records):** PROJECT_STATUS's header still named M12
   as the current milestone; DECISIONS (D-entry for T021a) linked a non-existent DATASETS anchor;
   DEPLOYMENT's GitHub Pages section said a custom tariff on Cost impact "shows 'not part of the
   static demo'", but on the synthetic demo the tariff form is disabled because no tariff
   geography exists ("Not configured"); and GitHub Pages answers deep links (`/alerts`) with
   **HTTP 404** while `404.html` renders the app correctly, which the docs did not say.
4. **Memory pressure is real on this machine:** one re-score attempt and one backend test failed
   while ~2 GB was free; this limits local full-scale work, not the code.

## Missing

1. **Authentication and authorization:** none (no auth code under `backend/src/wattwise/api`;
   SECURITY.md:3-6). Three write endpoints exist: feedback, upload, analyze.
2. **A public, server-backed real-data demo:** only the static synthetic demo is public.
3. **Short-anomaly detection:** 1–2 hour labelled segments are 70 % of LEAD segments and only
   13.0 % are found (stored LEAD report).
4. **Chunked data-quality audits** for full-scale datasets (Implemented but unverified, 3).
5. **The open M5b items**, still unscheduled (PROJECT_STATUS, "Next task" before T051): the 5 November event
   cluster, meters with very wide intervals, which artifact serves predictions (D039), and why
   the model detector's advantage reversed at full scale.
6. **Recruiter-facing walkthrough** with genuine results (the README links results but has no
   guided demo).

## Blocked by external services or licences

1. **Render** asks for a card for every service (owner, 2026-11-02); Koyeb's FAQ requires a card;
   Hugging Face's docs say Docker Spaces need a paid plan (T050 work log).
2. **Hosting the real data:** the dev database is **6.7 GB** (readings 5.9 GB, expectations
   684 MB), several times any free PostgreSQL tier (Render free: 1 GB; Neon free: 1 GB per
   project).
3. **Licences:** BDG2 is not redistributed (D014: sources disagree on MIT, CC BY 4.0, CC BY-SA
   4.0); LEAD is local-only (D022). A public real-data demo needs an owner decision on BDG2 and
   must exclude LEAD-derived labels.

## What this means for M13

- T052 must size hosting for a 6.7 GB database and a 49 MB model, or decide a smaller public
  subset; free tiers cannot hold the real data.
- The drift timeout and the unscalable audit backfill are confirmed defects for T056.
- T054 should start from the stored LEAD breakdown (1–2 h segments at 13 %).
- T058 is needed before any server-backed deployment that accepts writes.
