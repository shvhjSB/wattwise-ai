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

- **Feature leakage.** Lags, rolling statistics, imputation and scaling must be computed or
  fitted from training data only. T013 adds leakage tests for features.
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
