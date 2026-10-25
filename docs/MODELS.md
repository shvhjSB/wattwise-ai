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

## Current model (2026-10-25)

`train --promote` on the BDG2 sample saved the D026 model: LightGBM, all features, 200 trees.
It took about 22 s and made a 720 KB text model. Its recorded metrics equal the T014 results
(validation MAE 7.570, test MAE 7.490 kWh), and `evaluate` reproduced them exactly from disk.
It is valid for buildings with training data. For unseen buildings, seasonal-naive stays the
default (D026).
