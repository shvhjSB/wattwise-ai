# Model card: WattWise expected-consumption model

The model that tells WattWise what a meter **would** have used under the observed conditions. It
is the "expected" line in the explorer, the basis of the 90% interval and of every alert's
potential-excess estimate. It is **not** what raises alerts: the default alert source is a
rolling same-hour z-score (D030, D042).

Every figure here comes from the promoted artifact's own metadata or from
[EVALUATION.md](EVALUATION.md), with the section named. Results on synthetic data are not
real-world performance and are not reported here.

## Model details

| | |
|---|---|
| Artifact | `20261027T121334Z-eeec81e9592c`, the registry's `CURRENT` model ([MODELS.md](MODELS.md)) |
| Role | **The evaluation model** (D039): trained on the training window only, so its residuals on the validation and test windows are out of sample. The intervals and the stored expectations are calibrated on it. |
| Family | LightGBM gradient-boosted trees, full feature set (D036) |
| Settings | L1 (absolute-error) loss, 255 leaves, 1,779 trees (chosen by early stopping), learning rate 0.05, at least 100 rows per leaf, 80% of features per tree, seed 0 |
| Target | Consumption divided by the meter's mean over the week ending one horizon earlier (`rolling_mean_168h`); no prediction where that scale is missing or below 0.01 |
| Inputs | 33 columns (feature set 1, [FEATURES.md](FEATURES.md)): local calendar and holidays, observed weather, derived humidity, heating and cooling degrees, ERA5 radiation and cloud cover, sun position, and the meter's own history lagged at least 168 hours (one and two weeks earlier, four-week same-hour mean, rolling means and spread) |
| Horizon | 168 hours: every input is known at least one week before the hour predicted (D025) |
| Format | LightGBM text plus JSON, hash-verified, never unpickled (D027) |
| Code | Recorded in the artifact (`git_commit`, package and library versions) |

A **production refit** with the same settings, trained on training and validation windows
(`20261027T103133Z-ea3909799a6b`), scores slightly better on test (13.660 against 13.700 MAE on
common rows) but is not served: its validation residuals are in-sample, so intervals calibrated
on it would be too narrow (D039, D048).

## Intended use

- **Expected consumption for hourly electricity meters in commercial and campus buildings**, to
  compare against what was recorded, with a measured 90% interval.
- **Context for alerts** raised by the default detector: how far a reading was from what the model
  expected, and the energy above the interval's upper bound ("potential excess").
- **Analysis of an uploaded dataset** (`POST /inference/analyze`), with the caveat below.

## Out of scope

- **Verified savings, measurement and verification, or billing.** A potential excess is an
  estimate above an interval, not a verified saving; an anomaly is not confirmed waste.
- **Explaining causes.** The influences shown with an alert (TreeSHAP) are associations within the
  model, not causes; checks are phrased as hypotheses (D034).
- **Other energy types.** Trained and evaluated on electricity only.
- **Short histories.** Lag features need history: without about 10 days of a meter's readings
  there is no expectation (251 hours on the synthetic sample, D048).
- **Alerting on its own.** The model detector failed the pre-stated benchmark rule (D030, D042).

## Training data

[BDG2](DATASETS.md#building-data-genome-project-2-bdg2), cleaned variant, electricity: 1,148
eligible meters at 15 sites with a determined clock (D016, D020), 20,137,056 hourly readings
from 2016-01-01 to 2018-01-01 07:00 UTC (2016 and 2017 in local time). The model was fitted on a seeded 25% sample of quality-checked
training-window hours: **3,112,661 rows from 1,146 meters**, first hour 2016-01-11 11:00 UTC,
last 2017-06-30 23:00 UTC. Hours inside long flatlines were excluded from fitting (D035).

Splits are chronological (D018), end dates exclusive: training before 2017-07-01, **validation
2017-07-01 to 2017-10-01** (tree count and model choice), **test 2017-10-01 to 2018-01-02**
(scored once). No test hour is
earlier than any training hour.

BDG2 is campus-heavy (universities and similar), anonymised, and covers North America and Europe
in 2016 and 2017. These limits carry over to the model.

## Evaluation

**Test window, the promoted model's own report** (T011 harness, every row it scored;
[MODELS.md](MODELS.md)): MAE **13.720 kWh**, RMSE 76.700, bias −0.545 (under-predicts on
average), WAPE 8.8%, 2,283,087 rows scored, 154,899 with a reading but no prediction (no usable
scale).

**Against the seasonal-naive baseline** (the same hour one week earlier), on the test rows both
predicted ([EVALUATION.md, T043](EVALUATION.md#best-model-at-full-scale-t043-d036)):

| Comparison | Model MAE | Seasonal-naive MAE | Change |
|---|---|---|---|
| All 1,148 meters, test window | 13.700 | 16.705 | **18.0% lower** |
| Buildings not seen in training (287 held out, retrained without them) | 15.730 | 18.662 | 15.7% lower |
| Sites not seen in training (230 buildings held out) | 21.206 | 23.172 | 8.5% lower |

- **Per site**, 13 of 15 sites improve by 13–28%; Lamb (+0.1%) and Crow (−0.4%, 5,812 rows) are
  ties, and Moose improves by only 5.3%.
- **The model needs scale:** the same recipe trained on a 20-meter sample lost to
  seasonal-naive at full scale (−4.4%).

**The 90% interval** (rolling, relative, conformal; D032, D041): on the test window **87.2% of
readings fell inside it**, against 90% nominal. It is shown as measured, never as "calibrated".
A few meters still have very wide intervals; 24 of 1,148 meters have no stored expectation
(D052). Neither has been investigated further.

**On real anomalies** (LEAD 1.0 human labels, one annotator, agreement unmeasured; 173 meters,
July–December 2016; [EVALUATION.md, T044c](EVALUATION.md#detector-check-against-lead-labels-at-full-scale-t044c-d043)):
a model detector built on this recipe found 29.6% of labelled segments (the default rolling
z-score: 18.9%) but only 9.3% of its events touched a label (rolling z-score: 22.7%). This is why
the model gives context to alerts rather than raising them.

## Limitations

- **One dataset, two years, mostly campuses.** Accuracy on other building types, regions or years
  is unknown; the HKUST test (T041) has not been run.
- **Uploaded buildings** have no ERA5 enrichment and no holidays for unknown sites, so their
  expectations are an extrapolation that has not been validated (D048).
- **Clock changes:** a cluster of events on 5 November (the US clock change) has not been checked
  against the timestamp audit.
- **The interval undercovers slightly** (87.2% against 90%).
- **Feedback does not retrain the model.** Reviewers' labels are stored; no model learns from them
  (D047).

## Reproducing it

```bash
uv run python -m wattwise.ml.fullscale --evaluation-model --promote \
    --store ../data/processed/features-all --data ../data/processed/bdg2/cleaned-all
```

The command rebuilds the evaluation model deterministically and promotes it only if it reproduces
the recorded validation MAE exactly (15.267402). It needs the prepared BDG2 tables, the ERA5
enrichment and the feature store ([DATASETS.md](DATASETS.md), [EVALUATION.md](EVALUATION.md#full-scale-t042)).
