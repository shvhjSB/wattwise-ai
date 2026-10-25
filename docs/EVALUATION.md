# WattWise AI — Evaluation

How WattWise models are evaluated, and the results so far. Every result states the exact command,
data and code that produced it.
- **Baselines (T012):** real results on the BDG2 sample are [below](#baselines-t012).
- **ML models:** none has been trained yet (T014).

## Splits (T010)

Code: [`wattwise.ml.splits`](../backend/src/wattwise/ml/splits.py). Design decision: D018.

### Rules

1. **Time windows, never shuffled rows.** Every split is a set of UTC time windows, so a model is
   always tested on a period after the data it learned from.
2. **Windows are half-open: `start <= t < end`.**
   - A reading's timestamp marks the start of its interval (DATA_CONTRACT.md).
   - A reading belongs to a window only if its **whole interval** lies inside it:
     `[timestamp, timestamp + interval)`. The interval is the meter's most common step, the same
     rule the quality engine uses.
   - A daily reading that starts before a boundary and ends after it is therefore not used.
3. **An optional gap** is left out before the validation and test windows. Use it when features
   or labels look across the boundary, for example a forecast horizon.
4. **A building holdout** keeps chosen buildings, or whole sites, out of training and validation
   completely. They are tested only in the test window, as `test_unseen`.
5. **Every split checks itself.**
   - `make_split` re-checks every fold on the actual rows. A violation raises `LeakageError`;
     tests show these checks catch tampered folds.
   - The checks: no reading has two roles, every row lies in its window, earlier roles end
     before later roles start, and no held-out building is in training, validation or `test`.
   - A role with no readings is an error, which catches windows outside the data.
6. **Deterministic.**
   - The same config and data always give the same split, whatever the row order.
   - The manifest records the config and its SHA-256. `read_config` re-creates the config from a
     saved manifest and rejects a manifest whose config was edited.

### Chronological split

```
train_start            validation_start        test_start              test_end
|-------- train -------|gap|--- validation ---|gap|-------- test --------|
```

Validation is optional. Without `validation_start`, training runs up to `test_start - gap`.

### Rolling origin (expanding window)

```
fold-1  |========== train ==========|gap|-test-|
fold-2  |============== train ==============|gap|-test-|
fold-3  |================== train ==================|gap|-test-|
         train_start                  first_test_start + k * step
```

Fold *k* (from 0) is laid out as follows:
- **Test window:** `[first_test_start + k × step, … + horizon)`.
- **Training window:** `[train_start, its test start − gap)`.

A `step` shorter than the `horizon` makes test windows overlap from fold to fold; within a fold,
training still ends first. Durations are fixed lengths, not calendar months. Multiples of 7 days
give every window the same mix of weekdays.

### Holdout and roles

`Holdout(fraction, seed, group_by)` picks `round(fraction × groups)` buildings or sites, at least
one and never all. The draw uses `numpy.random.default_rng(seed)` over the sorted IDs of the
buildings present in the readings.

| Role | Buildings | Window |
|---|---|---|
| `train` | not held out | train |
| `validation` | not held out | validation |
| `test` | not held out | test: future period, seen buildings |
| `test_unseen` | held out | test: future period, unseen buildings |

- **Unseen buildings are tested only in the future window.** Testing them over the whole period
  would share time, weather and events with training, which is optimistic.
- **A site holdout (`group_by="site"`) is stricter than a building holdout.** Buildings on one
  site share a weather station and often schedules. Results for unseen buildings at seen sites
  must say so.

### Unused readings

Every reading without a role is counted, per fold, under one reason:

| Reason | Meaning |
|---|---|
| `held_out_before_test` | A held-out building's readings in the train or validation window |
| `gap` | The reading lies in a gap between two windows |
| `straddles_boundary` | The reading's interval crosses a window boundary |
| `outside_windows` | Before the first window or after the last |
| `unknown_interval` | The meter has a single timestamp, so its interval is unknown |

### Manifest

`write_manifest(split, path)` writes deterministic JSON. The evaluation harness (T011) saves it
with every result. It contains:

- `split_version`, `config_sha256` and `config`: the full config, with UTC timestamps and ISO
  8601 durations.
- `holdout_building_ids`.
- Per fold:
  - the windows
  - per role: rows, non-missing values, meters, buildings, and the first and last timestamps
  - the counts of unused readings by reason

### Example

```python
from datetime import UTC, datetime
from wattwise.ml.splits import (
    Chronological, Holdout, Role, SplitConfig, make_split, write_manifest,
)

config = SplitConfig(
    time=Chronological(
        train_start=datetime(2016, 1, 1, tzinfo=UTC),
        validation_start=datetime(2017, 7, 1, tzinfo=UTC),
        test_start=datetime(2017, 10, 1, tzinfo=UTC),
        test_end=datetime(2018, 1, 2, tzinfo=UTC),
    ),
    holdout=Holdout(fraction=0.2, seed=2016, group_by="site"),
)
split = make_split(readings, config, buildings)  # canonical tables
train = split.folds[0].rows(Role.TRAIN)
write_manifest(split, path)
```

**Observed on the BDG2 sample** (2026-10-24; 20 meters from 9 sites; the T009b default sample,
pipeline version 2). This shows split sizes only. It is not a model result.

| Role | Rows | Non-missing | Meters | First | Last |
|---|---|---|---|---|---|
| `train` | 196,820 | 186,731 | 15 | 2016-01-01T00:00Z | 2017-06-30T23:00Z |
| `validation` | 33,120 | 32,963 | 15 | 2017-07-01T00:00Z | 2017-09-30T23:00Z |
| `test` | 33,176 | 32,687 | 15 | 2017-10-01T00:00Z | 2018-01-01T06:00Z |
| `test_unseen` | 11,055 | 11,026 | 5 | 2017-10-01T00:00Z | 2018-01-01T04:00Z |

- The site holdout drew Cockatoo and Peacock: 5 meters. Their 76,645 earlier readings are
  unused.
- The test window ends on 2018-01-02 because the BDG2 local year ends up to 8 hours later in UTC.

### What splits do not protect against

- **Feature leakage.** Lags and rolling statistics must use only past readings, and imputation
  and scaling must be fitted on training rows only. The T013 features follow the leakage rules
  in [FEATURES.md](FEATURES.md), which tests prove. They fit nothing, so the model must fit
  any imputation and scaling.
- **Repeated looking at the test set.** Choose models and settings on validation or rolling
  folds. Use the test window once per reported result.
- **Shared context.** Unseen buildings at a seen site share weather and schedules with training
  buildings; use a site holdout for strict claims.

## Metrics and reports (T011)

Code: [`wattwise.ml.evaluation`](../backend/src/wattwise/ml/evaluation.py). Design decision: D021.

### What is scored

- **Evaluation roles only.** Only rows of `validation`, `test` and `test_unseen` are scored.
  Scoring `train` rows raises an error, because a training score is not an evaluation.
- **Exactly the role's rows.**
  - Predictions must be indexed by exactly the role's rows. A missing or extra row raises an
    error, so no forecaster can skip the hard rows unnoticed.
  - A row without a prediction is an explicit NaN and is counted as a missing prediction.
  - Rows without an actual value are counted and never scored.
- **One unit.** All scored rows must share one unit (D012).
- **Separate roles.** Seen buildings (`test`) and unseen buildings (`test_unseen`) are scored and
  reported separately, never pooled.

### Metrics

The error is **predicted − actual**, in the meters' unit (kWh for electricity).

| Metric | Definition | Notes |
|---|---|---|
| MAE | mean \|error\| | |
| RMSE | √ mean error² | Weights large misses more |
| Bias | mean error | Negative means under-prediction. An under-predicting baseline would overstate excess energy (T021) |
| WAPE | Σ\|error\| / Σ\|actual\| | Reported only when Σ\|actual\| ≥ `wape_min_total`, default 1 kWh. Otherwise the report gives the reason |

Each metric is reported at four levels:
- **Per meter.**
- **Per building**, pooled over the building's meters.
- **Overall**, pooled over all rows.
- **Macro**: the unweighted mean over meters, so small meters count as much as large ones. Macro
  WAPE averages only the meters whose WAPE is reported, and states how many.

For rolling-origin splits, each role also gets a summary across folds: the mean, minimum and
maximum MAE, the mean RMSE and the mean WAPE.

### The report

`evaluate(split, predictions, forecaster)` returns a report, and `write_report` writes it as JSON
and Markdown. Each report records:
- the forecaster's name and parameters
- **the code version:** the package version, git commit, and whether tracked files had
  uncommitted changes
- **the data:** a SHA-256 fingerprint of the readings' content, independent of row order, plus
  row and meter counts and the period
- **the split manifest** (T010), which can re-create the split
- the thresholds, every score and the fold summaries

The report holds no wall-clock time, and metrics are rounded to 6 decimals, so **the same inputs
give byte-identical reports** (tested).

**Speed, from a smoke run on 2026-10-24 on the BDG2 sample:**
- 13 rolling folds × 2 roles were scored in 2.3 s.
- Fingerprinting 5.3 M rows took 1.9 s.

The smoke run used a placeholder predictor, each meter's training mean. Its metrics are **not**
reported, because it is not a baseline. It also showed missing predictions being counted: the
placeholder cannot predict unseen buildings, and all 3,288 of those rows were reported as missing
predictions.

## Baselines (T012)

Code: [`wattwise.ml.baselines`](../backend/src/wattwise/ml/baselines.py). Design decision: D024.
These are the bar every model must beat.

| Baseline | What it predicts | Uses |
|---|---|---|
| `seasonal-naive-1w` | The same meter's reading exactly 168 h earlier: a one-week-ahead forecast | Only the reading one week back, never the hour itself or later (tested) |
| `hour-of-week-median` | The median of the meter's **training** readings for the same hour of the week, in the building's local time. An hour of the week without training data falls back to the meter's training median | Only training rows (tested). Local time keeps schedules aligned across daylight-saving changes (tested) |

Neither can forecast a building it has no data for, so unseen-building results wait for the
models (T014).

### Results on the BDG2 sample (2026-10-24)

```bash
uv run python -m wattwise.data.bdg2_prepare      # the default sample, pipeline version 2
uv run python -m wattwise.ml.baselines --data ../data/processed/bdg2/cleaned
```

- **Data:** BDG2 cleaned electricity, the seeded sample of 20 meters at 9 sites. 350,816 hourly
  readings, fingerprint `e2fc43c651eb2a03`.
- **Split:** chronological, config `dbcada8c8242`.
  - Train: 2016-01-01 to 2017-07-01.
  - Validation: to 2017-10-01.
  - Test: to 2018-01-02 UTC.
  - Each baseline is fitted on the training rows only.
- **Code:** the commit that adds this section. The full reports, per meter and per building,
  are written to git-ignored `data/processed/evaluation/baselines/`; repeat runs are
  byte-identical.

Errors are in kWh per hourly reading. Bias is predicted minus actual.

| Baseline | Role | MAE | RMSE | Bias | WAPE | Macro MAE | Macro WAPE (meters) | Scored | Missing prediction |
|---|---|---|---|---|---|---|---|---|---|
| seasonal-naive-1w | validation | 8.886 | 20.317 | −0.454 | 8.8% | 8.795 | 11.3% (20) | 43,361 | 417 |
| seasonal-naive-1w | **test** | **8.763** | 17.987 | +0.833 | **8.6%** | 8.711 | 14.7% (20) | 43,247 | 466 |
| hour-of-week-median | validation | 12.792 | 21.954 | +3.078 | 12.7% | 12.758 | 24.6% (20) | 43,778 | 0 |
| hour-of-week-median | **test** | **10.888** | 18.961 | +1.385 | **10.7%** | 10.849 | 16.5% (20) | 43,713 | 0 |

**Like for like:** the seasonal baseline has no prediction where last week's reading is missing,
about 1% of rows. On exactly the rows both baselines predict, the test MAE is **8.763**
(seasonal) against **10.918** (profile), on 43,247 rows; on validation it is 8.886 against
12.829.

**What this shows, and what it does not:**
- **The bar to beat is the seasonal-naive baseline:** test MAE 8.76 kWh, WAPE 8.6%. A model
  that does not beat it on the same split does not replace it (T014).
- **The profile over-predicts** (bias +3.1 kWh on validation, +1.4 on test). It averages
  winter and summer training weeks into one weekly shape, so it ignores weather and season.
  Weather features (T013) target exactly that.
- **Macro WAPE exceeds pooled WAPE** (test: 14.7% against 8.6% for the seasonal baseline).
  This suggests small meters have larger relative errors, since pooled WAPE is dominated by
  large meters. The per-meter reports allow this to be checked.
- **Holidays and term breaks:** the test quarter includes them, and neither baseline knows
  about them. Both are expected to err around them: the seasonal baseline in the week after a
  break, the profile during it. This is a hypothesis, not yet measured; holiday features come
  in T013.
- **Limits:** these are results for one seeded sample of 20 meters on cleaned data, not
  BDG2-wide or real-world performance. They are not anomaly-detection results.

## Models (T014)

`wattwise.ml.models` trains ML models on the T013 features and compares them with seasonal-naive
(D026). Models use the baselines' `fit`/`predict` interface, so the T011 harness scores them in
exactly the same way.

**Candidates.** Ridge regression, scikit-learn's HistGradientBoosting and LightGBM, each in two
variants:
- **full:** every feature group. The target is the reading divided by the meter's mean over the
  week ending 168 h before (`rolling_mean_168h`), and history features use the same scale. No
  meter identity is used, so the model can forecast unseen buildings from their own past.
- **conditions:** no consumption history. The scale is the meter's training mean, and the
  meter's training median for the local hour of the week is a feature. It cannot forecast
  buildings without training data.

**Procedure.**
1. All learned parts (scales, profiles, imputation, standardisation, the model) are fitted on
   training rows only. Ridge imputes medians with missing-value indicators; the tree models
   handle missing values natively. Predictions below zero become zero.
2. A small settings grid per family (ridge `alpha`; tree count for the boosted models) is
   scored on **validation**. The setting with the lowest validation MAE is kept, and the
   validation winner across all six family-variant pairs is the candidate.
3. The kept settings are scored **once** on test. Grid trials never touch the test window.
4. **Adoption rule:** the candidate replaces seasonal-naive only if its MAE is lower on the rows
   both predicted. Unseen buildings are judged separately: the best full model must beat
   seasonal-naive on held-out buildings under both a building holdout and a site holdout (25%,
   seed 0), with the settings chosen above.

```bash
uv run python -m wattwise.ml.models --data ../data/processed/bdg2/cleaned \
    --enrichment ../data/processed/era5/weather_enrichment.parquet
```

### Results on the BDG2 sample (2026-10-24)

The data and the chronological split are the same as for the baselines. Errors are in kWh per
hourly reading. Every number below is **expected-consumption accuracy with observed weather,
not forecast accuracy** (D025). The run takes about 5 minutes; repeat runs give byte-identical
reports, which are written to git-ignored `data/processed/evaluation/models/`.

**Validation grid** (MAE): ridge full 8.391 (any `alpha`); ridge conditions 13.570; HGB full
7.679 (200 trees) and 7.690 (500); HGB conditions 11.025 and 11.007; **LightGBM full 7.570
(200 trees)** and 7.608 (500); LightGBM conditions 10.969 and 10.920.

| Model (chosen setting) | Validation MAE | Test MAE | Test RMSE | Test bias | Test WAPE | Test missing prediction |
|---|---|---|---|---|---|---|
| seasonal-naive-1w | 8.886 | 8.763 | 17.987 | +0.833 | 8.6% | 466 |
| ridge full (α 0.1) | 8.391 | 8.414 | 15.734 | −0.067 | 8.2% | 415 |
| HGB full (200) | 7.679 | 7.637 | 14.022 | +0.333 | 7.4% | 415 |
| **LightGBM full (200)** | **7.570** | **7.490** | **13.903** | +0.211 | **7.3%** | 415 |
| ridge conditions (α 100) | 13.570 | 11.950 | 19.453 | +2.231 | 11.7% | 0 |
| HGB conditions (500) | 11.007 | 10.061 | 16.909 | +2.634 | 9.9% | 0 |
| LightGBM conditions (500) | 10.920 | 10.134 | 17.085 | +2.657 | 9.9% | 0 |

**Against seasonal-naive on the rows both predicted** (MAE reduction; negative is worse):

| Model | Validation | Test | Building holdout, unseen | Site holdout, unseen |
|---|---|---|---|---|
| ridge full | +7.3% | +4.0% | −5.0% | −2.0% |
| HGB full | +15.1% | +12.8% | +0.4% | −12.4% |
| **LightGBM full** | **+16.3%** | **+14.6%** (7.486 vs 8.764, 43,000 rows) | +0.1% (7.451 vs 7.461) | −14.4% (15.368 vs 13.434) |
| conditions models | −23% to −53% | −15% to −37% | no prediction | no prediction |

The held-out buildings were 5 at Eagle, Gator and Hog (building holdout), and the 5 buildings
of Hog and Lamb (site holdout). On the seen buildings of those holdouts, the full models still
beat seasonal-naive by 6–20% on test.

**Decision (D026):**
- **Seen buildings: LightGBM full (200 trees) is adopted.** It was the validation winner, and
  on test it reduces MAE by 14.6% against seasonal-naive on common rows. It is better on 17 of
  20 meters (per-meter test MAE), and its macro MAE is 7.43 against 8.71.
- **Unseen buildings: not adopted; seasonal-naive stays.** The best full model only ties
  seasonal-naive on the building holdout (+0.1%), and is 14.4% worse on the site holdout.
- **No-history models are not adopted.** All are clearly worse than seasonal-naive: a
  training-period weekly profile plus weather does not capture these meters' changes over time.

**What this shows, and what it does not:**
- The gain comes from combining recent history with conditions. Every model without history
  loses to a one-week-old reading.
- **The counterfactual concern stays open for T016.** The adopted model uses history, so a
  sustained anomaly enters its inputs after a week (D025). T016 must handle that, for example
  by scoring residuals before the anomaly reaches the history window, or by excluding flagged
  periods from history. The no-history models are not good enough to replace it.
- Unseen sites behave differently (the site-holdout errors are larger for every method), and
  20 meters at 9 sites cannot show whether a model generalises to new campuses.
- **Limits:** one seeded sample of 20 meters on cleaned data, one split, fixed small grids. Not
  BDG2-wide or real-world performance, and not anomaly-detection results.

## Detector benchmark (T018)

**Synthetic benchmark: injected anomalies on real BDG2 readings.** The anomalies are made up, and
the consumption around them is real. Real data has its own unlabelled anomalies, so alerts
outside the injected windows are an **upper bound** on false alerts. These are not results on
human-labelled anomalies (that is T018b).

```bash
uv run python -m wattwise.ml.benchmark --data ../data/processed/bdg2/cleaned \
    --enrichment ../data/processed/era5/weather_enrichment.parquet
```

**Patterns**, each relative to the meter's level (its median reading in calibration):

| Pattern | Injection | Correct signature |
|---|---|---|
| spike | +100% for 2 h | `spike` |
| sustained | +30% for 3 days | `sustained` |
| long_sustained | +30% for 14 days | `sustained` |
| overnight | +30% in local hours 22:00–05:59, on 7 nights | `overnight_excess` |
| drift | a ramp from 0 to +50% over 7 days | `drift` |
| flatline | the first reading repeated for 24 h | `flatline` |
| dropout | zero readings for 30 h | `data_fault` |

**Procedure** (promoted model `20261025T070700Z-4cf91609c9ef`, seed 0):
1. **Calibration:** the model's validation quarter (Jul–Sep 2017), from uninjected data.
2. **Tuning:** October 2017, the first third of the test window. There are 12 replicates, each
   injecting one anomaly per meter, with patterns rotating across meters: 240 injections. Each
   replicate rebuilds the features, so the model's history sees the injection as it would in
   reality.
   - **Settings tried:** for both detectors, 16 settings (z_on 4, 5, 6 or 8; z_off 2 or 3;
     at least 3 or 6 hours).
   - **Choice:** the setting with the highest mean recall over patterns, within an alert budget
     of 0.5 alerts per meter-week outside injections. That budget is a product assumption.
3. **Evaluation:** Nov 2017 to 1 Jan 2018, 12 fresh replicates (240 injections), scored once for
   the chosen settings and the T016 default.
4. **Scoring:** an injection is found when an event of its meter overlaps it. Latency runs from
   the injection's start to the first overlapping hour. Coverage is the share of injected hours
   inside events. The signature is that of the event with the largest overlap.

The run takes about 6.5 minutes; a rerun reproduced every number.

**Tuning: best recall within an alert rate** (alerts per meter-week):

| Detector | ≤ 0.2 | ≤ 0.3 | ≤ 0.5 | ≤ 1.0 |
|---|---|---|---|---|
| rolling-z | 75% | 75% | 75% | 75% |
| model | no setting | 52% | 80% | 85% |

**Chosen settings:**
- Model: open 4, continue 3, at least 6 hours. Recall 80% at 0.50 alerts in tuning, just
  within the budget.
- Rolling-z: open 4, continue 2, at least 3 hours. Recall 75% at 0.18 alerts.

**Evaluation (scored once):**

| Detector | Mean recall | Alerts per meter-week (injected runs) | Without injections |
|---|---|---|---|
| rolling-z (chosen = T016 default) | 72% | 0.39 | 0.46 |
| model, chosen | 81% | **0.97** | 0.97 |
| model, T016 default | 87% | 1.46 | 1.54 |

| Pattern | Injected | Model recall | Rolling-z recall | Model median latency (h) | Model coverage | Signature match (model / rolling-z) |
|---|---|---|---|---|---|---|
| spike | 34 | 76% | 56% | 0 | 100% | 85% / 84% |
| sustained | 34 | 85% | 71% | 0 | 69% | 55% / 38% |
| long_sustained | 35 | 89% | 86% | 0 | 51% | 77% / 30% |
| overnight | 35 | 91% | 83% | 13 | 27% | 50% / 59% |
| drift | 34 | 85% | 76% | 74 | 40% | 3% / 0% |
| flatline | 34 | 44% | 41% | 7 | 57% | 80% / 71% |
| dropout | 34 | 97% | 94% | 0 | 97% | 88% / 81% |

**Decision (D030): the model detector is not kept as the default alert source.**
- **Rule:** keep it only if it has the higher evaluation recall **and stays within the alert
  budget in tuning and evaluation**. It found more of every pattern, but its alert rate doubled
  out of sample, to 0.97 against a budget of 0.5. At alert rates both detectors reach, the
  rolling score had the higher recall (75% against 52% at up to 0.3).
- **Rule correction:** the rule as first written checked the budget in tuning only, and would
  have kept the model detector. It was tightened after the evaluation run, because a budget
  that fails out of sample is not met. Both results are in the report.

**What this shows, and what it does not:**
- **What tuning bought:** tuning cut the model detector's alerts by a third (1.46 to 0.97)
  for 6 points of recall. The rest is calibration drift: a summer scale is too narrow for
  winter (D028).
- **Weak spots:**
  - **Drift** is usually found (85%), but late (median 74 hours) and is almost never labelled
    `drift` (3%). The signature rule needs a long, monotonic event, which detection rarely
    produces.
  - **Flatlines** are found 44% of the time. A stuck reading only shows when it departs from
    the expected load.
  - **Overnight excess:** events cover only 27% of the injected hours. Each night is a separate
    short event, and the injection is only "on" at night.
  - **Long anomalies (14 days):** 89% recall, but 51% coverage. Even with the pre-event
    reference, part of the period falls below the thresholds.
- **The default's limit:** the rolling score does not know the weather. A test on a strongly
  weather-driven synthetic load shows it missing a +60% two-day surge that the model detector
  finds exactly.
- **Limits:** 20 meters, one autumn and winter, injected shapes chosen by us, and an assumed
  budget. Real anomalies may look different. Human labels are T018b.
