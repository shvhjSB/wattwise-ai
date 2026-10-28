# Project status

**Last updated:** 2026-10-28 · **Current milestone:** M5b — Scale-up and model quality (M1–M5, M7 complete)

## Summary

The application foundation runs end to end locally, and CI checks it automatically on GitHub:

- **Backend:** a FastAPI service with a liveness endpoint (`GET /api/v1/health`) and OpenAPI
  docs. It passes pytest, ruff and strict mypy. Dependencies are locked across platforms in
  `backend/uv.lock`, and the build backend is pinned too.
- **Frontend:** a React + TypeScript + Vite + Tailwind shell. It calls the API through a typed,
  runtime-validated client and shows loading, online and error-with-retry states. It passes
  type checking, ESLint (including accessibility rules), Prettier and Vitest, and builds for
  production.
- **CI:** a GitHub Actions workflow (`.github/workflows/ci.yml`) runs all backend and frontend
  checks on Ubuntu 24.04 for pushes to `main` and for pull requests. It uses SHA-pinned actions,
  a checksum-verified uv download and lockfile-keyed caches. The first run on GitHub was green:
  [run 39951620258](https://github.com/shvhjSB/wattwise-ai/actions/runs/39951620258) for
  `6948af4`. CI reports results but does not block merges; `main` has no branch protection (D011).
- **Data contract (v1.0):** one canonical shape for readings, buildings and weather, with a
  validator that turns CSV uploads or in-memory tables into canonical form. It reports every
  structural problem with a stable code, the affected rows and a fix hint.
  [docs/DATA_CONTRACT.md](DATA_CONTRACT.md) documents it, and a test keeps the document truthful.
- **Synthetic sample data:** a deterministic, clearly labelled synthetic dataset in
  [data/sample/synthetic/](../data/sample/synthetic/README.md). It has 4 buildings, 8 weeks of
  hourly electricity and weather, and 6 injected anomalies with labels. It is for tests, the
  demo mode and synthetic benchmarks.
- **BDG2 acquisition:** a pinned, checksum-verified download of the BDG2 files (about 369 MB)
  into git-ignored `data/raw/bdg2/`, with provenance recorded in
  [data/manifests/bdg2.json](../data/manifests/bdg2.json). Licence evidence and data conventions
  are in [docs/DATASETS.md](DATASETS.md). The files were downloaded and verified on 2026-10-23.

- **Data quality:** an engine that runs after the contract and describes the data with nine checks
  (gaps, missing values, coverage, negatives, zero runs, flatlines, extreme values, intensity and
  more) in deterministic JSON and Markdown reports ([docs/DATA_QUALITY.md](DATA_QUALITY.md)). On
  the synthetic sample it finds exactly the two injected data faults
  ([example report](reports/synthetic-data-quality.md)).

- **BDG2 timestamp audit:** BDG2's local timestamps follow a **different clock per site**.
  - **Electricity:** 11 wall-clock sites, 4 fixed-offset (standard) sites including Fox, and 4
    undetermined, excluded (385 buildings).
  - **Weather:** standard time at all 19 sites.
  - The verdicts are evidence-based, pinned, and re-checkable with
    `python -m wattwise.data.bdg2_audit` (D016, D020, [DATASETS.md](DATASETS.md)).

- **BDG2 metadata corrections (T009c, D020):**
  - **Fox's time zone:** corrected to `America/Phoenix`, because Arizona has no daylight saving
    time. The readings passed a zone check that rejected all 18 other sites when each was wrongly
    "corrected". This recovers 135 eligible meters.
  - **Wolf's longitude:** the sign is fixed.
  - **Regions:** each site's country and region is pinned, for holidays, prices and carbon
    later.

- **BDG2 preprocessing:** `python -m wattwise.data.bdg2_prepare` converts the download into
  canonical Parquet tables in git-ignored `data/processed/bdg2/`.
  - It also writes an exclusion log with a reason for every meter not used, a quality report and
    a manifest recording the metadata corrections.
  - The outputs are byte-identical across runs (D017).
  - The current run (pipeline version 2) used a seeded sample of 20 of 1,148 eligible meters
    from 9 sites: 350,816 readings, 95.65% coverage
    ([DATASETS.md](DATASETS.md#preparing-bdg2-for-analysis)).
- **Leakage-safe splits:** `wattwise.ml.splits` builds chronological and rolling-origin splits
  from explicit UTC windows, optionally holding out buildings or whole sites. Held-out buildings
  are tested only in the future window. Every split re-checks itself on the actual rows, raises
  `LeakageError` on any violation, and records a deterministic manifest (D018,
  [EVALUATION.md](EVALUATION.md)).
- **Evaluation harness (T011, D021):** `wattwise.ml.evaluation` scores any forecaster's
  predictions on a split.
  - **Metrics:** MAE, RMSE, bias, and WAPE only when total actual consumption is at least 1 kWh.
    They are reported per meter, per building, overall and as macro averages.
  - **Rules:** only evaluation roles are scored, predictions must cover exactly their rows, and
    missing predictions are counted.
  - **Reports:** JSON and Markdown, embedding the split manifest, a data fingerprint and the
    code version. The same inputs give byte-identical reports.
- **Supplementary data evaluated (T007b, D019):** every gap BDG2 leaves now has a recommended,
  source-verified option, or is stated as unfillable
  ([DATASETS.md](DATASETS.md#supplementary-data-evaluation-t007b)).
  - **Labels:** LEAD 1.0, human anomaly labels on 200 BDG2 meters in 2016, which join to our
    data exactly.
  - **Carbon factors:** eGRID2016, DESNZ, SEAI and the ECCC National Inventory Report.
  - **Prices:** EIA, DESNZ and CSO.
  - **Weather:** ERA5 solar radiation; humidity derived from BDG2.
  - **Calendar:** holidays and sun position.
  - **Other buildings:** Building 59 (sub-metered) and HKUST (independent).
  - **Metadata errors found in BDG2:** two "US/Eastern" sites are in Canada, and Fox and Wolf
    had the errors corrected in T009c.
  - **LEAD labels acquired and joined (T007c, D022):**
    - 1,438,672 usable hourly label rows on 173 BDG2 buildings in 2016, with 31,166 anomalies.
    - Of those anomalies, 16,848 have LEAD readings that match BDG2's raw data, so those labels
      are trusted.
    - Kept locally only, by owner decision.
  - **Weather enrichment acquired (T007d, D023):** ERA5 radiation and cloud cover for the 15
    located sites (Open-Meteo, `models=era5`), plus humidity derived from BDG2's observations
    for all 19 sites.
    - Both alignment checks passed at every site and in all 8 quarters. Solar-noon per-site
      medians were −8.6 to +2.0 minutes. The ERA5 temperature phase against BDG2's observed
      temperature was −0.50 to +0.30 h, stable across quarters.
  - **M2 data is complete.** Still to acquire later, when their tasks run: T021a (carbon and
    price tables), T040 (Building 59) and T041 (HKUST).

- **Baselines (T012, D024):** the first real results, on the BDG2 sample's test quarter (Oct–Dec
  2017).
  - Seasonal-naive: MAE 8.76 kWh per hour, WAPE 8.6%.
  - Hour-of-week profile: MAE 10.89 kWh, WAPE 10.7%.
  - **Seasonal-naive is the bar** every model must beat
    ([EVALUATION.md](EVALUATION.md#baselines-t012)).

- **Features (T013, D025):** `python -m wattwise.ml.features` builds feature set 1: 32
  versioned features in five groups (calendar, holidays, weather, sun, consumption history)
  ([FEATURES.md](FEATURES.md)).
  - **Leakage:** conditions never describe a later interval. History uses only readings at least
    the horizon (default one week) before the target. Tests show nothing changes before
    cutoff + horizon, and history changes from exactly then; the real data agrees.
  - **Missing data stays explicit:** NaN plus flags, nothing fitted or filled. On the BDG2
    sample, 25% of rows have no sun, holiday or ERA5 features (Eagle and Gator have no
    coordinates), observed weather is 0.55–0.76% missing, and history 5–6%.
  - **Deterministic:** byte-identical outputs, independent of row order; 350,816 rows in about
    7 s.

- **Models (T014, D026):** `python -m wattwise.ml.models` trains ridge, HistGradientBoosting
  and LightGBM, with and without consumption history. Settings and the winner are chosen on
  validation, and test is scored once ([EVALUATION.md](EVALUATION.md#models-t014)).
  - **Adopted for seen buildings: LightGBM with all features.** Test MAE 7.49 kWh against 8.76
    for seasonal-naive (−14.6% on the rows both predict); better on 17 of 20 meters.
  - **Not adopted for unseen buildings:** a tie on a building holdout (+0.1%) and 14.4% worse
    on a site holdout. Seasonal-naive stays the default there.
  - **No-history models lose to seasonal-naive** (15–37% worse on test). History absorbing
    sustained anomalies remains a known issue for T016.
  - These are expected-consumption results with observed weather, on one 20-meter sample; not
    forecast accuracy, and not anomaly detection.
- **Model registry (T015, D027):** `python -m wattwise.ml.registry train|evaluate|list|promote`
  saves models as versioned, git-ignored artifacts in `artifacts/models/`
  ([MODELS.md](MODELS.md)).
  - **Safe to load:** LightGBM text plus JSON only, never pickle. Every file is hash-checked,
    and the artifact and feature-set versions must match.
  - **Atomic:** versions are written to a staging folder and renamed into place. Promotion
    replaces a pointer atomically after verifying the version, and old versions stay for
    rollback. Without a promoted model, loading raises a clear "no model" error.
  - **Promoted now:** the D026 LightGBM model. Its recorded metrics (test MAE 7.490) were
    reproduced exactly by re-evaluating it from disk.
- **Anomaly detection (T016, D028):** `python -m wattwise.ml.detection` turns
  observed-minus-expected residuals into events ([DETECTION.md](DETECTION.md)).
  - **Method:** robust scores (median and MAD from the model's validation quarter). Hysteresis
    (open at 4, continue at 2), gap bridging, and persistence or a spike to keep an event.
  - **Long events:** after a week, they are scored against the meter's own pre-event week, so
    a sustained anomaly the model starts to absorb stays one event (tested).
  - **BDG2 sample, Oct–Dec 2017:** 355 events covering 11.9% of scored hours; byte-identical on
    a re-run.
  - **Too many alerts for operators, for measurable reasons:** heavy-tailed residuals (3.0% of
    calibration hours at |z| ≥ 4) and summer-to-winter drift (7.2% in the detection quarter).
    Thresholds are untuned until T018, so the list is for review, not an alert feed. Events are
    anomalies to investigate, not confirmed waste.
- **Signatures (T017, D029):** each event gets transparent pattern labels with their evidence.
  - **Labels:** data fault, flatline (stuck or not truly hourly meter), spike, overnight excess,
    drift, sustained, or unclassified.
  - **Precedence:** meter problems come first, so they are never shown as consumption.
  - **BDG2 test quarter:** 16 of 355 events are meter problems. Gator's whole-day "lows" are
    days where the raw data repeats one value every hour, a daily total spread over 24 hours.
    In T016 these were first read as possible holidays.
  - **Unclassified:** 65% of events, mostly 4–23 hours long, reported as such rather than
    forced into a pattern.
- **Detector benchmark (T018, D030):** `python -m wattwise.ml.benchmark`. Known anomalies of 7
  patterns are injected into real BDG2 readings: a **synthetic benchmark**, with 240
  injections to tune and 240 to evaluate once ([EVALUATION.md](EVALUATION.md#detector-benchmark-t018)).
  - **Model detector:** found more of every pattern (81% mean recall against 72%). But its alert
    rate doubled out of sample, to 0.97 per meter-week against a budget of 0.5.
  - **Rolling same-hour z-score:** stayed at 0.39, and had the higher recall at matched alert
    rates.
  - **So the rolling z-score is now the default alert source.** The BDG2 test quarter has 100
    events (2.1% of scored hours) instead of 355. The model detector remains available, and the
    model still provides expected consumption.
  - **Known limit of the default:** it does not know the weather, and misses a weather-masked
    surge the model finds (tested). T019 tests a season-adaptive scale for the model.
  - **Decision rule:** tightened after the evaluation run; the first version would have kept
    the model detector. Both are reported.
- **LEAD human-label check (T018b, D031):** **real data, human labels without measured
  agreement.** Trusted labels only, on 173 meters, July–December 2016, with a model trained on
  January–May.
  - **Rolling z-score:** hour precision 11.5% (chance 1.5%); 18.9% of labelled segments found;
    event precision 22.7%.
  - **Model detector:** 4.5%, 21.2% and 7.1%. This check's model was weaker than
    seasonal-naive, so it does not represent the adopted model.
  - **Little agreement overall:** 70% of the labels last 1–2 hours, which the persistence rules
    mostly ignore. Nothing was tuned on the labels.
- **Prediction intervals (T019, D032):** split-conformal intervals around expected consumption,
  with coverage **measured** on the test quarter ([EVALUATION.md](EVALUATION.md#prediction-intervals-t019)).
  - **The default is rolling recalibration**, scaled by the meter's recent level: nominal 90%,
    measured 86.7%.
  - **The others:** fixed relative 85.8%, fixed absolute 83.3%. Rolling is also the narrowest
    and the most even across meters (worst meter 76%, against 45–56%).
  - **None is "calibrated":** November, the first winter month, under-covers for every method.
    Intervals are about a third of the mean reading wide.
- **Season-adaptive model detector (T019b, D033):** the model's residuals are scaled by the
  meter's recent level and a rolling robust spread, then re-run through the T018 benchmark
  under the same pre-stated rule.
  - **Partial improvement:** out-of-season alert growth falls from ×1.9 to ×1.45.
  - **Still not adopted:** 0.71 alerts per meter-week in evaluation (budget 0.5), and recall
    69% against 72% for the rolling z-score.
  - **The rolling z-score stays the alert source.** The model serves expected consumption,
    intervals and impact.
- **Alert explanations (T020, D034):** every event gets an evidence bundle and a
  plain-language explanation.
  - **Contents:** the detector's comparison, the model's expectation with its rolling 90%
    interval and measured coverage, whether the model agrees, the signature evidence, the top
    influences (LightGBM TreeSHAP in kWh, labelled as associations, not causes) and a check to
    make.
  - **Wording guard:** no causal, certain or "waste" wording, enforced by tests and by the
    command.
  - **BDG2 test quarter:** all 100 events are explained. In 20 of them the weather-aware model
    finds every hour normal, and the explanation says so.
- **Full scale (T042, D035):** all 1,148 eligible meters at 15 sites (20.1 million readings) are
  now usable, not just the 20-meter sample.
  - **Feature store:** float32, built in batches. It matches the in-memory features exactly on
    the sample's 350,816 rows.
  - **Quality mask:** drops 9.5% of readings (runs of a day or more of one repeated value)
    from training.
  - **The bar at full scale:** seasonal-naive test MAE 15.72 kWh, WAPE 10.8%. The sample's 8.6%
    was easier than BDG2 as a whole.
  - **Performance bug fixed:** a 5.1-hour baseline run (memory paging) now takes 10 minutes,
    with identical results.
- **Reference tables (T021a, D037):** real, cited carbon factors and electricity prices, done
  in parallel while T043 trained in the background.
  - **9 carbon-factor rows** (7 US eGRID subregions plus GB and IE, 2016/2017 where the source
    publishes that year) and **10 price geographies** (8 US states, GB, IE), each with its
    source, URL, retrieval date, licence and the SHA-256 of the file it was read from
    ([DATASETS.md](DATASETS.md#carbon-factors-and-electricity-prices-acquired-and-integrated-t021a)).
  - **US sites mapped to their eGRID subregion** by an actual point-in-polygon lookup (ray
    casting against the published subregion boundaries), not a guess.
  - **Ontario stays "not configured" for 2016/2017:** a prior task cited a value from an older
    NIR edition, but that edition's own file could not be found and hashed in this task, so it
    is not committed rather than taken on trust.
- **Excess, cost and carbon impact (T021, D038):** also done in parallel while T043 trained.
  - **`potential_excess_kwh`:** kWh strictly above a T019 interval's upper bound; a negative
    residual never counts, and a missing bound gives "unknown", never zero.
  - **Always labelled "potential", never "verified":** `ImpactStatus.VERIFIED` exists only for
    a future human-confirmed figure (T025); nothing here sets it.
  - **Wired into every T020 evidence bundle** (an `"impact"` section, and a sentence in the
    rendered explanation when the figure is positive).
  - **Priced per event's own BDG2 site, never mixed:** cost is computed only for one named
    geography at a time (mixing currencies would misstate a total); carbon sums safely across
    every geography.
  - **Corrected in T044a (D040):** the first sample-scale figures counted events that the
    signatures call meter problems (data faults and flatlines), which D029 forbids. At full
    scale they held 42% of the first total. Meter problems are now kept out of potential
    excess, cost and carbon, and reported on their own line.
- **Best model at full scale (T043, D036):** LightGBM, L1 loss, 255 leaves, 1,779 trees,
  **adopted and promoted** as the production model.
  - **Test MAE 13.700 vs seasonal-naive 16.705 (+18.0%)**, scored once on 2,261,050 rows. The
    production refit (train+validation) scores 13.660 (+18.2%) and is the saved artifact
    (`20261027T103133Z-ea3909799a6b`).
  - **The old D026 sample-trained model (20 meters) now loses to seasonal-naive** at full scale
    (17.434 vs 16.705, −4.4%): it never generalised past its training sample.
  - **Generalises to genuinely unseen sites**, reversing T014's sample-scale finding (a tie or
    a loss there): unseen buildings +15.7%, unseen sites +8.5%.
  - **13 of 15 sites improve 13–28%**; the other two are a small sample or an effective tie.
  - **What made this slow:** an untuned L1-loss grid point that took 46,970 s in isolation was
    dropped; two attempts to train models concurrently thrashed this machine's RAM and were
    reverted in favour of sequential training; the machine slept for about 17 hours mid-run
    without losing progress ([EVALUATION.md](EVALUATION.md#best-model-at-full-scale-t043-d036)).

- **Downstream pipeline at full scale (T044a, D039–D041):** intervals, both detectors,
  explanations and impact now run on all 1,148 meters, on the T043 model, in under 13 minutes
  per step (TreeSHAP influences take hours). Three defects the sample could not show were found and fixed:
  - **The pipeline could not run on the production refit** (it has trained on the validation
    window, so calibrating on it would be in-sample). The promoted model is now the same
    model trained on the training window only; it reproduced T043's validation MAE exactly
    (15.267402). Test MAE 13.720 against the refit's 13.676 (D039).
  - **Meter problems were counted as potential excess**, against D029: 42% of the first
    full-scale total (D040).
  - **"Echo weeks":** after an outage, the past-only level is about 0 a week later while
    consumption is normal, which made 31 meters' relative intervals wider than 500% of their
    mean reading (the worst 2,190 times). Rolling mean width at 90% fell from 819 to 76 kWh
    (D041).
  - **Results:** rolling intervals measure 87.2% coverage at nominal 90% (87.1% on the sample;
    still not calibrated), and rolling stays the default under D032's criteria. Alert load
    matches the sample: 0.369 and 0.953 events per meter-week (rolling z-score and model).
    Corrected potential excess: **558,722 kWh and 220,140 kg CO2e** over 5,084 counted events;
    308,410 kWh at 462 meter-problem events is reported apart
    ([EVALUATION.md](EVALUATION.md#downstream-pipeline-at-full-scale-t044a-d039-d040-d041)).

- **Detector benchmark at full scale (T044b, D042):** the T018 benchmark on all 1,148 meters
  (1,133 injections to tune on and 1,133 to evaluate on, against 240 on the sample), under the
  same pre-stated rule.
  - **The answer is the same: the rolling z-score stays the default.** Rolling z-score 70.0%
    recall at 0.341 alerts per meter-week; model 62.1% at 0.827; season-adaptive model 70.0% at
    0.735 (budget 0.5). The season-adaptive model would have passed the first, looser rule.
  - **One sample-scale finding reverses:** the model detector's recall advantage (81% against
    72%) is gone; tuned to the same budget it finds fewer (62% against 70%). The reason was not
    investigated.
  - **Made possible by two equivalences, both tested:** indexed injection (equal to the
    original on all seven patterns) and features rebuilt only for the rows used.
  - Nothing changes for users.

- **LEAD check at full scale (T044c, D043):** **real data, human labels without measured
  agreement.** A model trained at full scale on January-May 2016 (all 1,171 raw meters) forecasts
  the labelled meters better than seasonal-naive (MAE 17.35 against 19.72).
  - As a detector it finds more labelled segments than the rolling z-score (29.6% against
    18.9%) and is less precise (event precision 9.3% against 22.7%, 3.4 times the events).
  - It improves on the labelled-meters model on every measure. The rolling z-score stays the
    default (D030, D033).
  - The model-based numbers of the labelled-meters rerun differ a little from D031 (3.8% against
    4.5% hour precision); the cause was not isolated.

## Completed tasks

| ID | Title | Completed |
|---|---|---|
| T001 | Repository audit, project records and hygiene | 2026-10-23 |
| T002 | Backend foundation (FastAPI, settings, liveness, tooling) | 2026-10-23 |
| T003 | Frontend foundation (Vite, React, TS, Tailwind, typed client) | 2026-10-23 |
| T004 | CI baseline (GitHub Actions, uv lock, SHA-pinned workflow) | 2026-10-23 |
| T005 | Canonical data contracts and CSV upload format | 2026-10-23 |
| T006 | Deterministic synthetic fixture generator | 2026-10-23 |
| T007 | BDG2 acquisition tooling and dataset documentation | 2026-10-23 |
| T008 | Data-quality engine and report | 2026-10-23 |
| T009a | BDG2 timestamp-convention audit | 2026-10-24 |
| T009b | BDG2 preprocessing pipeline | 2026-10-24 |
| T010 | Leakage-safe split utilities | 2026-10-24 |
| T007b | Supplementary dataset evaluation | 2026-10-24 |
| T009c | BDG2 site metadata corrections | 2026-10-24 |
| T011 | Evaluation harness and metrics | 2026-10-24 |
| T007c | LEAD 1.0 anomaly labels (local, joined to BDG2) | 2026-10-24 |
| T007d | Weather enrichment (ERA5 radiation, derived humidity) | 2026-10-24 |
| T012 | Seasonal and historical baselines | 2026-10-24 |
| T013 | Leakage-safe feature engineering | 2026-10-24 |
| T014 | ML forecaster vs baselines | 2026-10-25 |
| T015 | Model artifacts, metadata and registry | 2026-10-25 |
| T016 | Residual-based detector and event grouping | 2026-10-25 |
| T017 | Anomaly signature rules | 2026-10-25 |
| T018 | Injected-anomaly benchmark | 2026-10-25 |
| T018b | Detector check against LEAD human labels | 2026-10-25 |
| T019 | Prediction intervals | 2026-10-25 |
| T019b | Season-adaptive model detector, re-benchmarked | 2026-10-25 |
| T020 | Alert explanations | 2026-10-25 |
| T042 | Full-scale data, memory-efficient features and quality masking | 2026-10-25 |
| T021a | Sourced carbon-factor and price reference tables | 2026-10-26 |
| T021 | Excess energy, cost and carbon estimates | 2026-10-27 |
| T043 | Best model at full scale | 2026-10-27 |
| T044a | Downstream pipeline at full scale (evaluation model, intervals, detection, explanations, impact) | 2026-10-28 |
| T044b | Detector benchmark at full scale | 2026-10-28 |
| T044c | LEAD human-label check with a full-scale H1-2016 model | 2026-10-28 |

## Current task

None. Waiting for the owner to continue.

## Next task

**T022 — Alert prioritisation** (M8): a documented, transparent ranking of alerts that
uses the potential-impact estimates (D038) without presenting them as verified savings. See
[ROADMAP.md](ROADMAP.md#t022--alert-prioritisation).

Open from M5b, not scheduled: the 5 November event cluster (check against the clock audit), a
few meters whose intervals are still very wide, which artifact serves predictions (D039), and
why the model detector's recall advantage on the sample reversed at full scale.

## Milestone progress

| Milestone | Tasks | Done |
|---|---|---|
| M1 Foundation | T001–T004 | 4 / 4 |
| M2 Data contracts and acquisition | T005–T007, T007b, T007c, T007d | 6 / 6 |
| M3 Validation and preprocessing | T008, T009a, T009b, T009c, T010 | 5 / 5 |
| M4 Baselines | T011–T012 | 2 / 2 |
| M5 Improved model | T013–T015, T041 | 3 / 4 |
| M5b Scale-up and model quality | T042, T043, T044a, T044b, T044c | 5 / 5 |
| M6 Anomaly detection | T016–T018, T018b, T040 | 4 / 5 |
| M7 Explainability and uncertainty | T019, T019b, T020 | 3 / 3 |
| M8 Business impact | T021a, T021, T022 | 2 / 3 |
| M9 API and persistence | T023–T027 | 0 / 5 |
| M10 Frontend workflows | T028–T033 | 0 / 6 |
| M11 Integration | T034–T035 | 0 / 2 |
| M12 Operations and docs | T036–T039 | 0 / 4 |

## Blockers

None.

The `workflow`-scope push blocker was resolved on 2026-10-23. At the owner's request, `shvhjSB`'s
`gh` token was refreshed with the `workflow` scope (device-flow approval by the owner). The
global active account was then switched back to `aman-agntworksai`. This repo still commits and
pushes only as `shvhjSB` (D006).

## Development environment

| Component | Status |
|---|---|
| Python 3.13 + `backend/.venv` | Verified (T002). Managed by uv since T004 |
| uv 0.12.24 (winget `astral-sh.uv`) | Verified 2026-10-23: `uv sync --locked` and all backend checks pass |
| Node 24 / npm 11 | Verified (T003) |
| PostgreSQL 18.6 (service `postgresql-x64-18`, local connections only) | Verified 2026-10-23 (D007) |
| Docker Desktop 4.96.3 (engine 29.9.2, Compose v5.6.1, WSL2) | Verified 2026-10-23 after the restart: `docker run --rm hello-world` succeeded |
| GitHub push identity `shvhjSB` (scopes: repo, workflow, gist, read:org) | Verified 2026-10-23 by pushing `.github/workflows/ci.yml` |

## Known risks

| Risk | Affects | Mitigation |
|---|---|---|
| The push identity is pinned only in this clone's `.git/config` | Every push from another clone | Repeat the D006 setup in any new clone. The commands are in WORK_LOG (T002) |
| The repository is public | Every commit | Diff review before every commit. No secrets or data |
| BDG2 licence: four sources state MIT, CC BY 4.0 or CC BY-SA | T038 (public display) | Handled conservatively (D014): attribution, no redistribution of raw or derived data. Public display of BDG2-derived results is an owner decision at T038 |
| 4 of 19 BDG2 sites (385 buildings, including Rat with 305) have an undetermined electricity clock and are excluded | T009b and later | Excluded rather than guessed (D016). Fox was a metadata error, corrected with a falsifiable check (D020). Per-building classification for mixed sites such as Rat is possible later |
| LEAD 1.0 has no licence on GitHub, and the Kaggle rules forbid redistribution | T018 | Owner decision (D022): local evaluation only, never committed or redistributed, cited. Data lives only in git-ignored folders (tested) |
| LEAD's readings differ from BDG2's at 46% of labelled anomalies | T018b (done) | Trust a label only where the readings match (per-row flag); report the others separately (D022) |
| Supplementary sources differ by country and year; 4 BDG2 sites have no location | T021a, T007d | Per-site sourced tables; unlocated sites get "not configured", never a guess (D019) |
| BDG2 interval start/end cannot be determined from the data | T009b and later | Interval-start assumed explicitly: at most a 1-hour labelling uncertainty (D016). Recorded in every manifest |
| The default BDG2 sample is 20 meters from 9 sites, not stratified | T012 and later | Results are reported for the sampled sites only. `--sample-meters 0` uses all 1,148 eligible meters (D017) |
| BDG2 metadata may hold more errors like Fox's and Wolf's | Joins by location or time zone | Corrections are pinned with evidence and refuse changed data; a time-zone correction must pass the zone check (D020) |
| BDG2 "cleaned" data still has flatlines (12 of 20 sampled meters) and gaps | T012, T016 | Shown in the quality report; baselines and detectors must handle gaps and flag flatlines as data issues, not waste |
| Splits cannot stop features from looking ahead, or repeated use of the test window | T014 | T013 features are proven leakage-safe by tests (D025); model selection on validation or rolling folds only (D018) |
| Weather features use the observed weather of the target hour | T014 reporting | Results are expected-consumption accuracy, not forecast accuracy; say so with every result (D025) |
| History features absorb a sustained anomaly after the horizon | Long events | T016 scores events older than a week against the meter's pre-event week (D028); that reference ignores weather changes since the event began |
| Some BDG2 meters hold daily totals spread evenly over 24 hours (e.g. Gator_public_Geraldine) | Training, calibration, detection | Labelled `flatline` by T017, never consumption (D029). Masking such days from training and calibration is a candidate improvement |
| The model detector's alert rate doubles out of season (summer calibration, winter detection) | Alerts | The rolling same-hour z-score is the default alert source (D030); T019 tests a season-adaptive scale |
| The default rolling z-score does not know the weather | Strongly weather-driven buildings | Documented and tested: it can miss weather-masked anomalies the model finds. `--detector model` is available; T019 aims to combine both (D030) |
| The adopted model does not generalise to unseen sites on this sample | Uploads of new buildings | Seasonal-naive stays the default for buildings without training data (D026) |
| GitHub LFS bandwidth for future re-downloads | Re-fetching BDG2 | Verified local copies are never re-downloaded; HTTP 403/429 messages explain quota limits |
| ESLint pinned to 9 and TypeScript to 6 by plugin compatibility | Future upgrades | Upgrade triggers recorded in D008 |
| Pinned action SHAs, uv version and uv checksum do not update themselves | Security updates | Deliberate upgrades under the two-week rule. A uv upgrade changes three places together (D011) |
