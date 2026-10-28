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

## Detector check against LEAD labels (T018b)

**Real data, human labels without measured agreement (LEAD 1.0).** LEAD's annotators marked
anomalous hours on BDG2 meters in 2016. How often annotators agree has never been measured, so
a label is one person's judgement, not ground truth. Only labels whose LEAD reading equals
BDG2's raw reading are scored (D022). LEAD data stays local and is never committed; only these
aggregate figures are published.

```bash
uv run python -m wattwise.data.bdg2_prepare --variant raw --sample-meters 0
uv run python -m wattwise.ml.lead_check --data ../data/processed/bdg2/raw \
    --labels ../data/processed/lead/labels.parquet \
    --enrichment ../data/processed/era5/weather_enrichment.parquet
```

**Procedure (chronological; nothing is tuned on the labels):**
- **Readings:** BDG2's **raw** variant, which is what LEAD labelled, for LEAD's 173 meters.
- **A separate model:** LEAD's year is inside the adopted model's training period. So this
  check trains the adopted settings (LightGBM, all features) on **January–May 2016**,
  calibrates the model detector on **June**, and detects from **July to the end of 2016**.
- **Detectors:** both, with their standard settings (D030).
- **Scoring:**
  - **Hours:** precision and recall of hours inside events, against labelled anomaly hours.
  - **Segments:** a run of consecutive labelled hours counts as found if any event overlaps it.
  - **Events:** an event is true if it overlaps a labelled anomaly hour, and false if its
    labelled hours are all normal. Events with only untrusted or unlabelled hours are left
    unjudged.

**Labels in the detection window:**
- 728,575 label rows on 173 meters, of which 10,989 are untrusted.
- 2,089 trusted anomaly segments, with a median of 1 hour. 1,465 last 1–2 hours, 536 last
  3–23 hours, and 88 last a day or more.
- The chance precision (the anomaly share of trusted hours) is 1.5%.

**Results (2026-10-25, about 3 minutes; a rerun reproduced them byte for byte):**

| Detector | Hour precision | Hour recall | Hour F1 | Segment recall | Event precision | Events per meter-week |
|---|---|---|---|---|---|---|
| rolling-z (default) | **11.5%** | 13.8% | **12.6%** | 18.9% | **22.7%** | 0.43 |
| model | 4.5% | 20.9% | 7.4% | 21.2% | 7.1% | 1.35 |

| Detector | Segments of 1–2 h | 3–23 h | 24 h or more |
|---|---|---|---|
| rolling-z | 13.0% | 31.9% | 36.4% |
| model | 16.0% | 31.9% | 43.2% |

**What this shows, and what it does not:**
- **Little agreement with these labels.**
  - Both detectors find about a fifth of the labelled segments.
  - Most of their events do not touch a labelled hour: 77% of the rolling score's judged
    events, 93% of the model's.
  - Their precision is still well above chance: 7.7 times for the rolling score, 3 times for
    the model.
- **The labels are mostly very short:** 70% of segments last 1–2 hours. The detectors require
  persistence (3 or 6 hours) unless a deviation is extreme, by design (D028). They find a
  third or more of the longer segments. Whether short labels are actionable for operators is
  an open question, not a finding.
- **This check's model is weak, so its detector results do not describe the adopted model.**
  Trained on five winter and spring months, it forecasts July–December 2016 *worse* than
  seasonal-naive: MAE 22.08 against 19.57 kWh on 747,207 common rows. The adopted model (D026)
  had a full year of training and beat seasonal-naive by 14.6%.
- **The rolling z-score is the better detector against these labels:** about twice the hour
  precision and three times the event precision, at a third of the alerts. That agrees with
  the T018 decision (D030).
- **Limits:**
  - one annotation effort with unmeasured agreement
  - 2016 only
  - labels trusted only where the readings match
  - the alert-rate and persistence choices were made in T016–T018 without these labels, and
    they shape the result

## Prediction intervals (T019)

`wattwise.ml.intervals` puts split-conformal intervals around the promoted model's expected
consumption (D032). An interval is predicted ± q × s:

| Method | Scale s | q |
|---|---|---|
| absolute | 1 (kWh) | Per meter, from the calibration window |
| relative | The meter's mean over the week ending a week earlier (`rolling_mean_168h`, past-only) | Per meter, from the calibration window |
| rolling | As relative | Per meter, **recomputed daily** from the 28 days ending 7 days before the day (past only; the lag keeps an anomaly from widening its own interval at once) |

- **Quantile:** q is the conformal quantile of |actual − predicted| / s: the
  ⌈(n + 1)(1 − α)⌉-th smallest of n scores, from windows the model did not train on.
- **"Calibrated":** only when test coverage is within ±2 points of nominal overall, and in every
  month with at least 1,000 rows.
- **Lower bounds** are clipped at zero.

```bash
uv run python -m wattwise.ml.intervals --data ../data/processed/bdg2/cleaned \
    --enrichment ../data/processed/era5/weather_enrichment.parquet
```

### Results on the BDG2 sample (2026-10-25)

Promoted model `20261025T070700Z-4cf91609c9ef`. Calibration on the validation quarter
(Jul–Sep 2017); assessment on the test quarter (Oct 2017 to 1 Jan 2018). About 20 s; a rerun was
byte-identical. In the calibration window itself, the fixed methods cover exactly as constructed
(80.1%, 90.1%, 95.1%).

**Test coverage at nominal 90%:**

| Method | Coverage | Oct | Nov | Dec | Meters within ±2 points | Worst / best meter | Mean width | Width / mean reading | Interval score |
|---|---|---|---|---|---|---|---|---|---|
| absolute | 83.3% | 88.9% | 80.4% | 80.4% | 5 of 20 | 44.7% / 99.5% | 34.4 kWh | 33.4% | 64.3 |
| relative | 85.8% | 90.1% | 83.8% | 83.3% | 6 of 20 | 56.2% / 99.3% | 36.7 kWh | 35.7% | 60.7 |
| **rolling** | **86.7%** | 90.7% | 82.0% | 87.3% | 7 of 20 | **76.4%** / 93.2% | **33.0 kWh** | 32.0% | **59.0** |

| Nominal | absolute | relative | rolling |
|---|---|---|---|
| 80% | 72.8% | 75.6% | 77.2% |
| 90% | 83.3% | 85.8% | 86.7% |
| 95% | 89.0% | 91.7% | 91.7% |

**What this shows, and what it does not:**
- **No method is calibrated.** At nominal 90% they reach 83–87%. October, next to the summer
  calibration window, is close to nominal (89–91%). November, the first winter month, falls
  to 80–84% for every method.
- **Scaling with the recent level helps** (+2.5 points over absolute), but most of the gap is
  not level: the errors themselves grow in winter.
- **Rolling recalibration is the best of the three:** the highest coverage, the narrowest
  intervals and the best interval score. Above all, it is far more even across meters (worst
  meter 76% against 45–56%). Its 7-day lag makes it react a week or more late, which shows in
  November.
- **Intervals are wide:** about a third of the mean reading at nominal 90%. This bounds how
  small an excess T021 can claim with confidence.
- **Not tuned:** the window and lag settings were not chosen on these test months.
- **Limits:** 20 meters, one autumn and winter. Rolling has 583 test rows without an interval
  (too few recent scores); the fixed methods have 415 (no prediction or scale).

## Season-adaptive model detector (T019b)

**Synthetic benchmark: injected anomalies on real BDG2 readings** (the T018 procedure, with the
same windows, seeds, grid and budget). The question: does T019's season-adaptive scale make the
model detector good enough to be the alert source?

- **The `model-adaptive` score:**
  - The relative residual (actual − expected) / level, where the level is the meter's recent
    mean (`rolling_mean_168h`, past-only).
  - It is centred and scaled by its median and 1.4826 × MAD over the meter's 28 days ending
    7 days before each day. Only out-of-sample residuals count, and the scale is at least 1% of
    the level.
- **Long events:** they keep the pre-event reference.
- **The rule, fixed before the run (D030):** keep a model detector only with higher
  evaluation recall than the rolling z-score, within the alert budget in tuning and in
  evaluation.

The run takes about 8 minutes. The rolling z-score and static model results reproduced T018
exactly.

| Detector (chosen setting) | Tuning recall | Tuning alerts | Evaluation recall | Evaluation alerts | Without injections |
|---|---|---|---|---|---|
| rolling-z (open 4, continue 2, 3 h) | 75% | 0.18 | **72%** | **0.39** | 0.46 |
| model, static scale (open 4, continue 3, 6 h) | 80% | 0.50 | 81% | 0.97 | 0.97 |
| **model-adaptive** (open 5, continue 3, 3 h) | 69% | 0.49 | 69% | 0.71 | 0.81 |

Alerts are per meter-week outside injections; the budget is 0.5.

| Pattern | rolling-z | model | model-adaptive |
|---|---|---|---|
| spike | 56% | 76% | 65% |
| sustained | 71% | 85% | 74% |
| long_sustained | 86% | 89% | 83% |
| overnight | 83% | 91% | 77% |
| drift | 76% | 85% | 74% |
| flatline | 41% | 44% | 24% |
| dropout | 94% | 97% | 85% |

**Best tuning recall within an alert rate:** model-adaptive 50% (≤ 0.3), 69% (≤ 0.5) and 78%
(≤ 1.0); rolling-z 75% throughout; no model variant gets below 0.29.

**Decision (D033): the rolling z-score stays the default alert source.**
- **The adaptive scale works only partly.** The static model detector's alert rate grew
  ×1.9 out of season (0.50 to 0.97); the adaptive one grows ×1.45 (0.49 to 0.71). That is
  still over budget.
- **And it loses recall:** 69% against 72% for rolling-z, and lower than the static model on
  every pattern. A likely reason, as a hypothesis: after its 7-day lag, its 28-day window
  starts to include the anomaly, which inflates the scale. Long sustained coverage falls to 43%.
- **On the BDG2 test quarter (`--detector model-adaptive`):** 194 events covering 2,202 hours,
  against 100 and 916 for rolling-z.
- **What remains of the model's role:** expected consumption, and the intervals and impact
  built on it (T019, T021). Unless a later idea passes this same rule, alerts come from the
  rolling z-score.

## Full scale (T042)

Every result above came from a seeded sample of 20 meters at 9 sites. T042 makes all eligible
meters usable on this machine (15 GB RAM, 16 cores), and records the baselines at full scale
(D035).

```bash
uv run python -m wattwise.data.bdg2_prepare --sample-meters 0 --output ../data/processed/bdg2/cleaned-all
uv run python -m wattwise.ml.scale features --data ../data/processed/bdg2/cleaned-all \
    --enrichment ../data/processed/era5/weather_enrichment.parquet
uv run python -m wattwise.ml.scale baselines --data ../data/processed/bdg2/cleaned-all
```

- **Data:** 1,148 eligible meters at 15 sites, 20,137,056 hourly readings (1,187,658 missing),
  prepared in 93 s.
- **Feature store:**
  - Features are built in batches of 100 meters and written as float32 parquet parts with
    hashes. That takes 517 s, with a peak working set of 6.1 GB.
  - On the 20 sample meters, all 350,816 rows and all 32 features equal the in-memory
    computation exactly. A test checks the same on synthetic data.
- **Quality mask** (training targets and calibration only; detection sees every reading):
  - No negative readings and no 24-hour zero runs remain in BDG2's cleaned data.
  - What remains is long runs of identical readings. Runs of 6–23 hours hold 180k readings,
    and many are steady loads on coarse meters (resolution 0.1 to 6 kWh). Runs of 24 hours or
    more hold 1.79M readings, and 199 meters have more than 10% of their readings in them.
  - **The mask drops runs of 24 hours or more:** 1,794,952 readings (9.5%) on 376 meters,
    with 195 meters over 10%.
- **Performance bug found and fixed:**
  - The first full-scale baseline run took **5.1 hours**. With 20 million identifiers held as
    strings, the process peaked at 6.3 GB and the machine paged to disk.
  - Category identifiers gave **identical reports in 10 minutes** (5.5 GB peak). On 100 meters
    they cut memory 5.8 times, also with identical reports.

**Baselines at full scale** (the T012 split; kWh per hourly reading):

| Rows scored | Baseline | Validation MAE | Test MAE | Test WAPE | Test macro MAE | Meters |
|---|---|---|---|---|---|---|
| all rows | seasonal-naive-1w | 17.89 | **15.72** | **10.8%** | 15.78 | 1,132 |
| all rows | hour-of-week-median | 28.31 | 21.63 | 14.8% | 21.73 | 1,132 |
| quality rows | seasonal-naive-1w | 19.31 | 16.74 | 10.3% | 16.44 | 1,021 |
| quality rows | hour-of-week-median | 29.48 | 22.54 | 13.9% | 22.14 | 1,082 |

- **"Quality rows":** masked readings are treated as missing, for targets and history alike.
  That is why fewer meters are scored: a seasonal-naive forecast needs last week's reading.
- **The sample was easier than BDG2 as a whole.** Its seasonal-naive test WAPE was 8.6%,
  against 10.8% at full scale. **The bar for T043 is seasonal-naive at full scale: test MAE
  15.72 kWh, WAPE 10.8%.**

## Best model at full scale (T043, D036)

LightGBM, searched on validation across loss function and tree size, with early stopping, on a
seeded 25% sample of quality-checked training hours (3,214,532 of 20,137,056 rows; validation
and test use every row); 8 threads.

```bash
uv run python -m wattwise.ml.fullscale --store ../data/processed/features-all \
    --data ../data/processed/bdg2/cleaned-all --promote
```

**Search (validation, all rows):**

| Loss | Leaves | Trees (early stop) | Validation MAE | Against seasonal-naive (common rows) | Seconds |
|---|---|---|---|---|---|
| L2 | 63 | 227 | 16.326 | 16.235 vs 18.779 (+13.6%) | 52 |
| L2 | 255 | 128 | 16.202 | 16.124 vs 18.779 (+14.1%) | 53 |
| **L1** | **255** | **1,779** | **15.267** | **15.203 vs 18.779 (+19.0%)** | 66,459 (the machine slept for about 17 h mid-fit; see below) |
| Huber | 63 | 609 | 15.634 | 15.570 vs 18.779 (+17.1%) | 91 |
| Huber | 255 | 239 | 15.565 | 15.501 vs 18.779 (+17.5%) | 75 |

**Chosen: L1 loss, 255 leaves, 1,779 trees.** The no-history variant scores far worse on
validation (25.289 vs 17.910 naive, −41.2%): consumption history remains essential at scale.

**Test (scored once): MAE against seasonal-naive on the rows both predicted**

| | Model | Seasonal-naive | Change | Rows |
|---|---|---|---|---|
| Chosen model | 13.700 | 16.705 | **+18.0%** | 2,261,050 |
| Chosen model, quality rows | 13.781 | 16.823 | +18.1% | — |
| **Production refit** (train + validation windows) | **13.660** | 16.705 | **+18.2%** | — |
| Sample-trained model (D026, the old 20-meter model) | 17.434 | 16.705 | **−4.4%** | — |

- **The old sample-trained model loses to seasonal-naive at full scale.** It was fit on 20
  meters from 9 sites and does not generalise to the other 1,128 meters — exactly the problem
  T042/T043 exist to fix. It is no longer the registry's promoted model.
- **Cross-check from the saved artifact's own T011 report** (a different denominator: every row
  the model itself scored, not only rows where seasonal-naive also had a valid lag): MAE
  13.676, RMSE 76.608, bias −0.454, WAPE 8.8%, 2,283,087 scored rows, 154,899 without a
  prediction. The two MAE figures (13.700 vs 13.676) differ only because they are computed over
  slightly different row sets; both describe the same promoted model.

**Per site (test, rows and MAE against seasonal-naive):**

| Site | Rows | Model vs naive | Change |
|---|---|---|---|
| Bull | 244,740 | 15.519 vs 21.447 | +27.6% |
| Wolf | 79,008 | 16.511 vs 22.232 | +25.7% |
| Gator | 137,939 | 11.353 vs 14.758 | +23.1% |
| Cockatoo | 245,539 | 9.022 vs 11.422 | +21.0% |
| Bear | 196,008 | 12.428 vs 15.529 | +20.0% |
| Peacock | 79,512 | 10.486 vs 13.121 | +20.1% |
| Eagle | 207,139 | 15.924 vs 19.364 | +17.8% |
| Bobcat | 56,025 | 9.468 vs 11.279 | +16.1% |
| Hog | 310,509 | 21.814 vs 25.960 | +16.0% |
| Mouse | 2,755 | 24.099 vs 28.258 | +14.7% |
| Panther | 229,944 | 10.604 vs 12.263 | +13.5% |
| Fox | 295,135 | 10.657 vs 12.269 | +13.1% |
| Moose | 25,498 | 31.388 vs 33.133 | +5.3% |
| Lamb | 145,487 | 10.958 vs 10.969 | +0.1% (tie) |
| Crow | 5,812 | 30.321 vs 30.206 | −0.4% (tie, 5,812 rows) |

13 of 15 sites improve by 13–28%; Crow and Moose/Lamb are small-sample or effectively tied.

**Unseen buildings and sites** (same chosen settings, retrained without the held-out group):

- Building holdout (287 held-out buildings): seen 13.232 vs 16.064 (+17.6%); **unseen 15.730
  vs 18.662 (+15.7%)**.
- Site holdout (230 held-out buildings): seen 12.134 vs 14.964 (+18.9%); **unseen 21.206 vs
  23.172 (+8.5%)**.
- **This reverses T014's sample-scale finding.** At 20 meters the model tied on a building
  holdout and lost on a site holdout, so seasonal-naive stayed the default for buildings
  without training data (D026). At full scale the model beats seasonal-naive even on
  completely unseen sites, though by a smaller margin (+8.5%) than on seen data (+18.9%).

**Adopted: yes.** The validation-chosen model beats seasonal-naive on the test rows both
predict (the pre-stated rule). **Promoted: yes** — artifact `20261027T103133Z-ea3909799a6b` is
now the registry's current model, replacing the D026 sample-trained model.

**What made this slow, and the fixes applied (docs/DECISIONS.md, D036):**
- **The L1 loss's first attempt at 63 leaves took 46,970 s** (a separate benchmark run, not
  part of the final search): dropped from the grid in favour of 255 leaves, which reached a
  nearly identical validation MAE (15.283 vs 15.306 in that earlier run) in a twelfth of the
  time.
- **Two attempts at training multiple models concurrently were tried and reverted.** Running 2
  models at once (4 threads each) thrashed this machine's 15.3 GB RAM instead of using idle
  CPU, since each fit holds its own copy of the float32 input matrix; it was slower than
  training one model at a time with all 8 threads, and once even crashed the process. The final
  run trains sequentially.
- **The machine slept for about 17 hours mid-fit**, pausing the L1@255 trial without losing
  progress (the process resumed exactly where it left off) but adding that time to the trial's
  reported duration. A later run that must finish within a bounded window should keep the
  machine from sleeping.
- **Float32, not float64, inputs to LightGBM:** the feature store is float32 already; converting
  it to float64 before fitting doubled memory for no benefit to a tree model.

## Excess energy, cost and carbon impact (T021)

`wattwise.ml.impact` turns the hours above a T019 prediction interval's upper bound into kWh,
then prices them with a tariff and carbon-costs them with a `wattwise.data.reference` factor
(T021a) — both explicitly configured, never guessed. **Potential, not verified:** an anomaly is
not confirmed excess consumption, and nothing here is confirmed by a person
(`ImpactStatus.VERIFIED` exists for a future human-feedback label, T025).

```bash
uv run python -m wattwise.ml.impact --data ../data/processed/bdg2/cleaned \
    --enrichment ../data/processed/era5/weather_enrichment.parquet \
    --geography US-MROW --tariff-currency USD --tariff-rate 0.0986
```

- **Carbon is priced per event's own BDG2 site**, never one site's factor applied to another's.
  Cost is priced only for one named geography at a time: summing cost across geographies would
  mix currencies into a meaningless total.
- **A missing geography or carbon factor gives `None` ("not configured"), not zero and not a
  guess.** Eagle and Gator have no coordinates, so their events carry no carbon factor.

**BDG2 test quarter, rolling same-hour z-score (the default detector), 100 events** — *superseded: this run counted events the signatures call meter problems, and used the D026 model. The corrected full-scale figures are in [T044a](#downstream-pipeline-at-full-scale-t044a-d039-d040-d041) (D040).*

| Geography | Events | Potential excess (kWh) | Carbon (kg CO2e) |
|---|---|---|---|
| GB | 9 | 34.7 | 13.3 |
| US-AZNM | 3 | 23.2 | 11.1 |
| US-ERCT | 19 | 1,881.8 | 865.6 |
| US-FRCC | 10 | 764.9 | 352.6 |
| US-MROW | 20 | 2,035.7 | 1,151.8 |
| US-NYUP | 8 | 40.9 | 5.5 |
| US-RFCE | 6 | 171.5 | 59.3 |
| not configured (Eagle, Gator) | 25 | 814.0 | 0.0 |

**Total: 5,766.7 kWh potential excess, 2,459.2 kg CO2e potential carbon**, across all 9
geographies. Cost was priced only for US-MROW (Hog's site, 20 events) at the EIA Minnesota 2016
commercial rate (T021a): 2,035.7 kWh × $0.0986/kWh.

## Downstream pipeline at full scale (T044a, D039, D040, D041)

Every downstream result so far came from the 20-meter sample. T044a runs the pipeline on all
1,148 meters, with the model T043 chose, and re-checks each result under the rules already fixed
(D030, D032). Three defects the sample could not show were found and fixed on the way; the
results below are after the fixes, with the before-numbers where they differ.

```bash
# the evaluation model (D039): the T043 model trained on the training window only
uv run python -m wattwise.ml.fullscale --evaluation-model --promote \
    --store ../data/processed/features-all --data ../data/processed/bdg2/cleaned-all
# then, one at a time (each reads the store: --store ../data/processed/features-all
#   --data ../data/processed/bdg2/cleaned-all --output ../data/processed/fullscale-downstream/...)
uv run python -m wattwise.ml.intervals    ...
uv run python -m wattwise.ml.detection    ...                  # rolling z-score (default)
uv run python -m wattwise.ml.detection    ... --detector model
uv run python -m wattwise.ml.explanations ... --no-influences  # the influences: see below
uv run python -m wattwise.ml.impact       ... --explanations .../explanations.json \
    --geography US-MROW --tariff-currency USD --tariff-rate 0.0986
```

| Step | Time | Peak memory |
|---|---|---|
| Evaluation model (retrain) | 4,292 s (training) | about 5 GB committed |
| Intervals | 737 s | 4.30 GB |
| Detection, rolling z-score | 110 s | 2.92 GB |
| Detection, model | 447 s | 4.12 GB |
| Explanations, without influences | 339 s | 4.72 GB |
| Explanations, with influences (first run) | 16,468 s, of which about 2.8 h the machine was in standby (system power log) | 4.71 GB |
| Impact (priced from saved explanations) | 29 s | 0.23 GB |

### The evaluation model (D039)

The T043 production refit has trained on the validation window, so intervals and the model
detector cannot be calibrated on it. The same model, trained on the training window only,
**reproduced T043's validation MAE exactly (15.267402, with identical RMSE, bias, WAPE and
counts)** and is now promoted. Test MAE 13.720 (T011 harness), against the refit's 13.676. See
[MODELS.md](MODELS.md).

### Prediction intervals (T019 rerun, D041)

Rolling intervals calibrated on quality rows (D035), on rows with a usable scale (D041);
calibration 2017-07-01 to 2017-10-01, test 2017-10-01 to 2018-01-02. "Typical meter" is each
meter's mean width against its mean reading.

| Method | Nominal | Coverage | Meters within 2 points | Worst meter | Mean width (kWh) | Median width (kWh) | Interval score |
|---|---|---|---|---|---|---|---|
| absolute | 80% | 75.8% | 142 of 991 | 14.8% | 48.9 | 21.4 | 90 |
| absolute | 90% | 86.0% | 209 of 991 | 25.5% | 70.5 | 32.4 | 123.1 |
| absolute | 95% | 91.7% | 301 of 991 | 34.0% | 91.7 | 42.7 | 163 |
| relative | 80% | 76.9% | 162 of 991 | 17.2% | 45.7 | 22.5 | 84 |
| relative | 90% | 87.0% | 240 of 991 | 28.2% | 2,781.4 | 32.8 | 2,829.7 |
| relative | 95% | 92.5% | 306 of 991 | 40.1% | 4,357.6 | 44.0 | 4,422 |
| **rolling (default)** | 80% | 77.8% | 317 of 1,017 | 54.9% | 50.1 | 22.1 | 86 |
| **rolling (default)** | **90%** | **87.2%** | 367 of 1,017 | 58.2% | 76.4 | 31.8 | 122.8 |
| **rolling (default)** | 95% | 92.3% | 436 of 1,017 | 59.9% | 108.8 | 41.7 | 171 |

- **Coverage matches the sample.** Rolling at nominal 90% measures 87.2%, against 86.7% on the
  sample (T019). **Still not calibrated:** none of the methods is within 2 points of nominal
  overall and in every month. November, the first winter month, covers 84.5% for rolling.
- **D032's default stands.** Rolling has the highest coverage, the narrowest median width, the
  best interval score (by a hair) and is by far the most even across meters (the worst meter
  covers 58.2%, against 25.5% for absolute and 28.2% for relative). The decision is unchanged.
- **A typical meter's 90% interval is about 46% of its mean reading wide** (the sample's was
  about a third), with a 90th percentile of 147%.

**A defect found here (D041).** Before the fix, the rolling method's mean width at 90% was
**819.5 kWh against a median of 31.7**, and its interval score 867, because of "echo weeks": a
week of zero readings makes the past-only level about 0 a week later, while consumption is back
to normal. 31 of 1,017 meters had intervals wider than 500% of their mean reading and 4 wider
than 100,000%; the worst was 2,190 times the mean reading. On the two clearest meters, mean width
fell from 109,459 and 123,430 kWh to 82 and 108 after the fix (medians unchanged). After it:
mean width **76.4 kWh**, interval score **122.8**, coverage 87.1% → 87.2%; 148,892 rows now have
no interval because their level is not a usable scale. **Remaining:** the worst meter's interval
is still 468 times its mean reading, from a cause this task did not find.

### Detection (T016–T018 rerun)

Test window 2017-10-01 to 2018-01-02. The default is still the rolling same-hour z-score (D030);
the decision rule that chose it compares recall on injected anomalies, which is T044b's job. Here
only the alert load is re-measured.

| Detector | Events | Per meter-week | Event hours | Sample (T018) |
|---|---|---|---|---|
| Rolling z-score (default) | 5,546 | **0.369** (budget 0.5) | 53,145 = 2.2% of 2,433,767 scored hours | 0.39 |
| Model | 12,550 | **0.953** | 169,634 = 8.0% of 2,114,920 scored hours | 0.97 |

- **Both match the sample's alert rates** (over 1,132 and 991 meters). The model detector is
  still about double the budget.
- **Signatures, rolling z-score:** data fault 215, flatline 247, spike 1,750, overnight excess
  733, sustained 335, drift 1, **unclassified 2,265 (41%**, against 65% on the sample).
- **Events cluster on certain days** (the daily average is 60). 766 of the 5,546 (13.8%) start
  on 20–24 November, US Thanksgiving week; 147 start on 5 November (the US clock change) and
  149 on 23 December, each about 2.5 times the average; 814 (14.7%) start between 15 and 26
  December. The rolling z-score knows neither the calendar nor the weather, so holiday weeks
  are a likely explanation. For 369 events the model's top influence is `is_public_holiday`.
  These are patterns to investigate, not findings; the 5 November cluster in particular is
  worth checking against the clock audit (D016, D020).

### Explanations (T020 rerun)

- **All 5,546 events are explained**, 5,493 with a model expectation, and the command's wording
  guard (no causes, certainty or "waste") passed on all of them.
- **The interval held for 87.2% of hours in the detection window** (shown with every
  explanation).
- **Model agreement:** the weather-aware model agrees with the detector on 3,937 events,
  disagrees on 1,346 (every hour inside its interval, which the text says) and has no interval
  for 263 (80 before D041; the rest are echo-week hours, which now get none). On the sample,
  20% disagreed.
- **Most common top influences** (TreeSHAP, associations not causes; from the first full run,
  which is identical for the model): `same_hour_mean_4w` 2,568, `lag_168h` 1,893,
  `day_of_year_local` 500, `is_public_holiday` 369, `log_scale` 43. The final bundles were
  regenerated without influences (they do not depend on the intervals, and TreeSHAP takes hours).

### Excess energy, cost and carbon (T021 rerun, D040)

Rolling z-score, 5,546 events. **462 (8.3%) are meter problems** (data faults and flatlines), which
D029 says are never consumption; T021 had counted them. The first full-scale total was 1,002,572
kWh, **of which 425,193 kWh (42.4%) was meter problems**: two single hours alone were about
54,000 kWh each. Now they are kept out, and listed apart.

| Geography | Events counted | Potential excess (kWh) | Carbon (kg CO2e) |
|---|---|---|---|
| GB | 359 | 9,292.7 | 3,572.4 |
| IE | 176 | 4,419.9 | 1,931.5 |
| US-AZNM | 803 | 47,626.3 | 22,662.5 |
| US-CAMX | 375 | 24,578.4 | 5,907.5 |
| US-ERCT | 818 | 187,659.0 | 86,318.8 |
| US-FRCC | 608 | 63,356.7 | 29,208.1 |
| US-MROW | 652 | 120,292.5 | 68,064.2 |
| US-NYUP | 447 | 9,678.2 | 1,299.2 |
| US-RFCE | 141 | 3,401.4 | 1,175.8 |
| not configured (no coordinates, or Canada) | 705 | 88,417.0 | 0.0 |

**Total potential excess 558,721.9 kWh and 220,140.0 kg CO2e** over 5,084 counted events (from
1,002,572 kWh and 390,369 kg), plus **308,410 kWh above the bound at the 462 meter-problem
events, not counted.** Cost at the EIA Minnesota 2016 commercial rate, US-MROW only: **11,860.84
USD** over 652 events.

- **It is concentrated:** the 10 largest events hold 17.5% of the total, the largest 50 hold
  40.5% and the largest 200 hold 68.5%. Only 2,286 of the 5,084 counted events have any hour
  above the upper bound.
- **Still potential, not verified.** GB's figure fell from 121,227 to 9,293 kWh (92% of it was
  meter faults); ERCT's from 446,140 to 187,659.
- The sample-scale figures in the T021 section above (5,766.7 kWh, 2,459.2 kg CO2e) are
  superseded: they counted meter problems and used the D026 model.

### Not done here

- **T044b:** the injected-anomaly benchmark (the rule that decides the default detector).
- **T044c:** the LEAD human-label check with a full-scale model (done, see
  [below](#detector-check-against-lead-labels-at-full-scale-t044c-d043)).
- **The 5 November cluster and the remaining very wide intervals** are open questions.

## Detector benchmark at full scale (T044b, D042)

The T018 benchmark, unchanged in procedure and in decision rule (D030), on all 1,148 meters
with the evaluation model (D039). Known anomalies of 7 patterns are injected into real BDG2
readings, so this is a **synthetic benchmark on a real background**; alerts outside injections
are an upper bound on false alerts, because real data has its own unlabelled anomalies.

```bash
uv run python -m wattwise.ml.benchmark --data ../data/processed/bdg2/cleaned-all \
    --enrichment ../data/processed/era5/weather_enrichment.parquet \
    --store ../data/processed/features-all --replicates 1 \
    --output ../data/processed/fullscale-downstream/benchmark
```

- **Design.** One replicate per phase, which already injects one anomaly per meter: **1,133
  injections to tune on and 1,133 fresh ones to evaluate on** (15 more did not fit their
  window each time), against 240 and 240 on the sample. Seed 0. Calibration 2017-07-01 to
  2017-10-01, tuning 2017-10-01 to 2017-11-01, evaluation 2017-11-01 to 2018-01-02 (scored
  once). With about 1,100 injections, the standard error of a mean recall is about 1.4
  points, so differences under about 3 points are not meaningful.
- **Time.** Tuning 1,408 s, evaluation 538 s, the evaluation window without injections 467 s,
  plus about 5 minutes of setup; about 3.2 GB working set while it ran.

**Evaluation (scored once), each detector at the setting chosen in tuning:**

| Detector | Mean recall | Alerts per meter-week (budget 0.5) | Same, without injections | Sample (T018/T019b) |
|---|---|---|---|---|
| **rolling z-score** | **70.0%** | **0.341** | 0.395 | 72%, 0.39 |
| model | 62.1% | 0.827 | 0.856 | 81%, 0.97 |
| model, season-adaptive (T019b) | 70.0% | 0.735 | 0.839 | 69%, 0.71 |
| *model at the T016 default* | *72.2%* | *1.313* | *1.392* | |
| *model-adaptive at its default* | *74.6%* | *1.046* | *1.213* | |

**The rule gives the same answer as on the sample: neither model-based detector is kept; the
rolling z-score stays the alert source (D030, D033).**
- **Model:** recall is *lower* than the rolling z-score's (62.1% against 70.0%), and its alert
  rate exceeds the budget (0.827).
- **Season-adaptive model:** recall is level with the rolling z-score's (70.03% against
  69.95%, a difference far inside the noise), but its alert rate is 0.735, over the 0.5
  budget. **The first, looser rule (budget in tuning only) would have kept it**, which is the
  reason D030 tightened the rule.

**One finding reverses.** On the sample the model detector found more of every pattern (81%
against 72%). At full scale, tuned to the same budget, it finds *fewer* (62% against 70%).
At its T016 default it still has the higher recall (72.2%), but at 1.31 alerts per meter-week,
2.6 times the budget and 3.8 times the rolling z-score's alert rate. Why is not investigated.

**Recall per pattern, chosen settings (the share whose signature also matched, in brackets):**

| Pattern | Injected | rolling z-score | model | model-adaptive |
|---|---|---|---|---|
| spike | 162 | 58% (74%) | 63% (79%) | 69% (86%) |
| sustained | 161 | 68% (33%) | 52% (64%) | 60% (65%) |
| long sustained | 164 | 80% (31%) | 69% (67%) | 83% (68%) |
| overnight | 163 | 75% (70%) | 60% (44%) | 69% (52%) |
| drift | 160 | 71% (11%) | 64% (11%) | 76% (13%) |
| flatline | 163 | 43% (74%) | 42% (84%) | 45% (91%) |
| dropout | 160 | 94% (87%) | 85% (89%) | 87% (91%) |

- **What the rolling z-score does well and badly:** it finds a dropout 94% of the time and a
  long sustained excess 80%, but a flatline only 43% and a spike 58%.
- **The signature labels are weak for slow patterns:** a drift is found about 71% of the time
  and labelled `drift` only 11% of the time, whichever detector finds it, and a rolling
  z-score event for a sustained excess carries the `sustained` signature 33% of the time. An
  event can be right and its label wrong.

**Best tuning recall within an alert rate:**

| Detector | at most 0.2 | 0.3 | 0.5 | 1.0 |
|---|---|---|---|---|
| rolling z-score | 71% | 73% | 73% | 73% |
| model | none | none | 62% | 72% |
| model-adaptive | none | 45% | 65% | 70% |

At every alert rate the rolling z-score has the highest recall (or the only one at all below
0.5), and the model detectors reach their recall only at several times the rate.

**Not done:** more replicates (one gives about 1,100 injections per phase); and the benchmark
still does not say how the detectors do on *real* anomalies. T044c checks that with the LEAD
human labels.

## Detector check against LEAD labels at full scale (T044c, D043)

The T018b check (D031), unchanged in procedure, with the model trained at full scale.
**Real data, human labels without measured agreement (LEAD 1.0):** one annotator's judgement, on
173 labelled meters, July-December 2016. Both detectors run with their T018 default settings;
nothing is tuned on the labels.

```bash
uv run python -m wattwise.ml.lead_check --data ../data/processed/bdg2/raw \
    --labels ../data/processed/lead/labels.parquet \
    --enrichment ../data/processed/era5/weather_enrichment.parquet \
    --scale-from ../data/processed/evaluation/fullscale/fullscale.json \
    --output ../data/processed/fullscale-downstream/lead-scale
```

- **The model.** The T043 chosen settings (L1 objective, 255 leaves, 3,000 trees with early
  stopping), trained on a seeded 25% sample of the quality-checked January-May 2016 readings of
  **all 1,171 raw meters** (838,771 rows, not only the 173 labelled ones), with early stopping
  on June (187,918 rows). Training window strictly before the calibration month and the
  detection window. Early stopping chose **76 trees** (of up to 3,000), on this single month.
- **Forecast context** (the labelled meters, July-December 2016): MAE **17.354** against 19.719
  for seasonal-naive (12.0% lower). The D031 labelled-meters model was *worse* than
  seasonal-naive (21.197 against 19.719).
- **Time.** 268 s and a 5.6 GB peak working set for the full-scale check, 187 s for the
  labelled-meters rerun.

| Detector | Hour precision | Hour recall | Event precision | Segment recall | Events per meter-week |
|---|---|---|---|---|---|
| rolling z-score | 11.5% | 13.8% | 22.7% | 18.9% | 0.431 |
| model, full-scale model (T044c) | 4.2% | 27.1% | 9.3% | 29.6% | 1.465 |
| model, labelled-meters model (rerun now) | 3.8% | 24.6% | 7.2% | 26.3% | 1.658 |
| *model, labelled-meters model (D031, T018b)* | *4.5%* | | *7.1%* | *21.2%* | |

The chance hour precision (the share of scored hours that are labelled) is 1.5%.

**Labelled segments found, by length:**

| Detector | 1-2 h (1,465) | 3-23 h (536) | 24 h or more (88) |
|---|---|---|---|
| rolling z-score | 13.0% | 31.9% | 36.4% |
| model, full-scale | 23.2% | 42.7% | 55.7% |
| model, labelled-meters (rerun) | 20.2% | 39.2% | 48.9% |

**What the check says**
- **The full-scale model is a better model detector, and it is still the less precise one.** It
  finds more labelled segments (29.6% against 18.9% for the rolling z-score) at every length,
  but fewer of its events touch a label (9.3% against 22.7%), and it raises 3.4 times the
  events. Its hour precision is 2.8 times chance; the rolling z-score's is 7.7 times chance.
- **The full-scale model improves on the labelled-meters model on every precision and recall
  measure here**, and raises fewer events. A hypothesis, not tested: better forecasts leave
  smaller residuals where nothing is wrong. The improvement is modest: 0.4 points of hour precision, 2.1 points of event precision.
- **Both are low in absolute terms.** The rolling z-score finds about one labelled segment in
  five, the full-scale model about three in ten. 70% of labelled segments last 1-2 hours,
  which the persistence rules mostly ignore. Whether operators want 1-2 hour alerts is a
  product question.
- **The rolling z-score row is identical in all three runs** (it does not use the model).

**Discrepancy to note.** The labelled-meters model detector, rerun now, gives 3.8% hour
precision and 7.2% event precision (D031 recorded 4.5% and 7.1%), and its test MAE is 21.20
(D031: 22.08). The rolling z-score reproduces D031 exactly. The model-based numbers moved
because the pipeline changed after D031 (features and quality masking in T042, calibration
masking in T044a); **this was not isolated, so the cause is a hypothesis.**

**Limits**
- One annotator, agreement unmeasured; the labels are partial (unlabelled hours are not known
  to be normal), so **precision here is a lower bound** on the real share of useful alerts.
- 173 meters from the labelled sites; with one model fit and one early-stopping month, the
  differences of a few points between the two model rows are not strong evidence.
- Only labels whose LEAD reading equals BDG2's raw reading are scored (D022).
- A check, not a tuning step: the T018 defaults were not changed (D030 and D033 stand).

## Alert prioritisation (T022, D044)

`wattwise.ml.prioritisation` ranks alerts for review. **The score orders alerts; it is not a
probability, a verified saving or a measure of waste.** An anomaly is not confirmed waste, and
the impact component is the *potential* excess of T021.

**The formula.** Score = 100 x (0.4 impact + 0.2 persistence + 0.2 severity + 0.2 confidence),
each component between 0 and 1.

| Component | What it measures | 0 means | 1 means |
|---|---|---|---|
| impact | potential excess kWh above the upper bound (T021) | none | 20,000 kWh or more |
| persistence | flagged hours | 1 hour | 72 hours or more |
| severity | the detector's peak score | the threshold (4) | 100 or more |
| confidence | half: whether the model interval agrees with the detector (1 yes, 0 no, 0.5 no interval); half: the share of the event's hours flagged | all against | all for |

- **Impact, persistence and severity are logarithmic** (each doubling counts the same), because
  real peak scores run from 4 to 15 million and potential excess from 0 to 19,307 kWh; a linear
  scale would let one extreme alert fix the ordering.
- **Meter problems** (`data_fault`, `flatline`) are not consumption (D029, D040): their impact
  is 0, and they are marked `kind: meter_problem`. Alerts *below* the expected level have no
  excess above the bound, so their impact is 0 too (`kind: below_expected`). Both still rank on
  persistence, severity and confidence.
- **Cost and carbon do not enter the score.** A tariff is optional and per geography; mixing
  currencies would make the ordering depend on configuration.
- **Ties:** the score rounded to 2 decimals, then larger potential excess, more flagged hours,
  the earlier start, the meter id, then the later end. The order does not depend on the input
  order (tested).
- **The weights and caps are product assumptions, not fitted to labels.** They were set from
  the range of real alerts, not tuned to any outcome: the impact cap is just above the largest
  potential excess seen; the persistence cap is the 99th percentile of flagged hours (72)
  and the severity cap the 98th percentile of peak scores (100).

```bash
uv run python -m wattwise.ml.prioritisation \
    --explanations ../data/processed/fullscale-downstream/explanations-lean/explanations.json \
    --output ../data/processed/fullscale-downstream/priorities
```

**On the 5,546 full-scale alerts (all 1,148 meters, rolling z-score, evaluation model):**

- Scores run from 10.2 to 89.7 (median 33.9; 90th percentile 53.6).
- Median score by kind: 39.0 above expected (3,141 alerts), 29.1 below expected (1,943), 37.5
  meter problems (462).
- **The top of the list concentrates the potential excess.** Of all potential excess, the top 20
  alerts hold 22.3%, the top 100 hold 45.1%, the top 200 hold 61.2% and the top 500 hold 80.3%.
  Ranking by excess alone would put 68.5% in the top 200 (D040), so the score gives up about
  seven points of that to put persistent, sharp and corroborated alerts first.
- The top 100 are all above-expected alerts across 76 different meters; 42 of the top 500 are
  meter problems.
- The ranking is for **review order**, and nothing here shows that a higher-ranked alert is
  more likely to be a real problem: no labels were used, and the LEAD check (T044c) shows that
  the detectors themselves agree with one annotator only in part.

**Not done:** checking the order against human feedback (T025 adds the labels to do it);
per-geography cost or carbon in the ranking; a per-building roll-up.
