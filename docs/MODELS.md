# Model artifacts and registry

Module: `wattwise.ml.registry` · Decision: D027 · Task: T015

A trained model is saved as a versioned **artifact**: a folder the API can load without running
any code from it. The **registry** is the folder of artifacts plus a pointer to the promoted one.

```bash
uv run python -m wattwise.ml.registry train --data ../data/processed/bdg2/cleaned \
    --enrichment ../data/processed/era5/weather_enrichment.parquet --promote
uv run python -m wattwise.ml.registry evaluate --data ../data/processed/bdg2/cleaned \
    --enrichment ../data/processed/era5/weather_enrichment.parquet
uv run python -m wattwise.ml.registry list
uv run python -m wattwise.ml.registry promote <version>
```

`--root` (default `../artifacts/models`, git-ignored) selects another registry folder.

## Layout

```
artifacts/models/
  CURRENT                              the promoted version's name
  20261025T070227Z-4cf91609c9ef/       <created_at UTC>-<first 12 hex of the model's SHA-256>
    model.txt                          LightGBM's own text format
    state.json                         learned values besides the trees ({} for the full variant)
    metadata.json                      what the model is and how it was made (below)
```

## Metadata

| Field | Meaning |
|---|---|
| `artifact_version` | Layout version of the artifact ("1") |
| `version`, `created_at` | The folder name, and the UTC creation time |
| `model` | Name, family, variant, settings and seed |
| `feature_set_version`, `horizon_hours`, `feature_columns` | The features it needs (FEATURES.md), and its input columns in order |
| `min_scale`, `scale_rule` | How targets are scaled, and when no prediction is made |
| `training` | Data fingerprint and row count, the rows fitted on, meters, first and last training hour, and the split config with its SHA-256 |
| `code` | Package version, git commit, and whether the tree had uncommitted changes |
| `libraries` | lightgbm, numpy and pandas versions |
| `metrics` | Validation and test metrics from the T011 harness (MAE, RMSE, bias, WAPE, rows) |
| `files` | SHA-256 of `model.txt` and `state.json` |

**The artifact is exactly the evaluated model.** `train` fits on the split's training rows and
scores validation and test once, so the recorded metrics are out-of-sample. `evaluate`
rebuilds the features, re-scores the artifact on its recorded split, and fails unless it
reproduces the recorded metrics exactly. With different data it says so, and does not compare.

## Safety

- **Nothing is unpickled.** A pickle file can run arbitrary code when loaded. Artifacts hold
  only LightGBM text and JSON, so only LightGBM models can be saved. scikit-learn models
  (ridge, HistGradientBoosting) are refused, since they have no safe format.
- **Integrity before parsing:** `model.txt` and `state.json` must match the SHA-256 recorded in
  the metadata. The metadata is validated strictly (unknown fields are refused).
- **Compatibility:** an artifact made for another artifact or feature-set version, or a feature
  table missing a needed column, is refused with `IncompatibleModelError`.
- **Names:** only names of the form `YYYYMMDDTHHMMSSZ-<12 hex>` are accepted, so `CURRENT`
  cannot point outside the registry.

## Atomic writes and promotion

- **Saving:** a new version is written to a hidden staging folder, each file flushed to disk,
  then renamed into place. A failure removes the staging folder. Versions are never
  overwritten.
- **Promoting:** the version is verified first. Then `CURRENT` is replaced by an atomic rename;
  on any error the current model is unchanged. Old versions are kept, so promoting an older
  version rolls back.
- **No model:** without a promoted model, `load` raises `NoModelError`, and `evaluate` exits
  with "No model has been promoted". The API will report "no model available" (T024).

## Versions in the registry (2026-10-27)

| Version | What it is | Trained on | Role |
|---|---|---|---|
| `20261025T070700Z-4cf91609c9ef` | The D026 model: LightGBM, all features, 200 trees | 20 sample meters | Superseded. At full scale it loses to seasonal-naive (−4.4%, T043) |
| `20261027T103133Z-ea3909799a6b` | **The production refit** (D036): L1 loss, 255 leaves, 1,779 trees | Training and validation windows, 1,148 meters | The best model, but not the one downstream tools calibrate on (below) |
| `20261027T121334Z-eeec81e9592c` | **The evaluation model** (D039): the same settings and tree count | Training window only (to 2017-06-30), 1,146 meters | **Promoted** (`CURRENT`) |

**Why two models with the same settings (D039).** Intervals and the model detector are
calibrated on the model's validation window. The production refit has trained on that window,
so its residuals there are in-sample and would make every interval too tight. The evaluation
model never saw the window, so its residuals there are honest. `fullscale --evaluation-model`
rebuilds it deterministically and promotes it only if it reproduces the T043 study's recorded
validation MAE exactly (it did: 15.267402).

| Role | Evaluation model (promoted) | Production refit |
|---|---|---|
| Validation MAE | 15.267 (out-of-sample) | in-sample, not reported |
| Test MAE (T011 harness, 2,283,087 scored rows) | 13.720 | 13.676 |
| Test MAE against seasonal-naive on common rows (T043) | 13.700 | 13.660 |

The test difference is 0.3%: promoting the evaluation model costs almost nothing in accuracy.
It is valid for every meter with training data; for unseen buildings and sites see D036
(+15.7% and +8.5% against seasonal-naive).

```bash
uv run python -m wattwise.ml.fullscale --evaluation-model --promote \
    --store ../data/processed/features-all --data ../data/processed/bdg2/cleaned-all
```
