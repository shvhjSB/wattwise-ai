# Anomaly detection

Detector version: **1** · Module: `wattwise.ml.detection` · Decision: D028 · Task: T016

The detector turns the gap between observed and expected consumption into **events**. An event is
a period worth investigating; it is **not confirmed waste**. Its residual sum is a deviation from
the baseline used, not verified excess energy. T021 estimates potential excess with intervals.

```bash
uv run python -m wattwise.ml.detection --data ../data/processed/bdg2/cleaned \
    --enrichment ../data/processed/era5/weather_enrichment.parquet
```

It uses the promoted model (MODELS.md). It writes `events.csv`, `scores.parquet` (the score of
every detection hour), `summary.json` and `report.md` to git-ignored `data/processed/detection/`.
Repeat runs are byte-identical.

## Scores

For each meter and hour, residual = observed − expected, and

  z = (residual − median) / (1.4826 × MAD)

The median and MAD (median absolute deviation) are the meter's, from a **calibration window**
the model did not train on: the model's validation quarter. Detection runs on later rows only.
On training rows, the model's residuals are too small, so their scores would be wrong.

- **Scale floor:** the scale is at least 1% of the meter's mean absolute reading. A meter the
  model fits almost perfectly therefore cannot turn tiny deviations into alarms.
- **Meters without calibration rows** get no scores.

## Events

Each direction is detected separately: **high** (above expected) and **low** (below). Defaults:

| Setting | Default | Meaning |
|---|---|---|
| `z_on` | 4.0 | An event opens at a score of at least this |
| `z_off` | 2.0 | An open event continues while the score is at least this (hysteresis) |
| `max_gap_hours` | 2 | Gaps of up to this many hours (low scores or missing data) are bridged, merging adjacent windows |
| `min_hours` | 3 | An event is kept with at least this many flagged hours (persistence)… |
| `z_spike` | 8.0 | …or with one score at least this high (a spike) |
| `horizon_hours` | 168 | After this long, an event is scored against the pre-event reference (below) |
| `reference_weeks` | 4 | How many weeks back to look for a pre-event reading |
| `scale_floor_fraction` | 0.01 | The scale floor, as a share of the mean absolute reading |

These are **provisional and untuned**. The injected-anomaly benchmark (T018) evaluates them, and
the test quarter is not used to choose them.

Each event records:
- **Extent:** start, end (exclusive) and duration in hours
- **Hour counts:** flagged hours (score at least `z_off`), missing hours, and hours scored
  against the reference
- **Peak:** time, score and residual
- **Size:** the residual sum
- **`ongoing`:** whether the event reaches the end of the detection window

## Long events: the pre-event reference

The adopted model's history features look back at least one week (D025). After a week of
sustained excess, those features contain the excess, and the model starts to expect it. A long
anomaly would then fade away by itself after about a week.

**Fix:** once an event has lasted `horizon_hours`, the detector scores it against the meter's own
reading at the same hour of the week, in the last week **before the event started**. That
comparison has its own calibrated median and scale (seasonal-naive residuals in the calibration
window). Tests show the effect directly: a 3-week step the model absorbs after a week stays
**one 504-hour event** with the reference, and is cut off after 168 hours without it.

The reference ignores weather changes since the event began. That is the price of a baseline
the anomaly cannot contaminate.

## Results on the BDG2 sample (2026-10-25)

Promoted model `20261025T070700Z-4cf91609c9ef`. Calibration: 2017-07-01 to 2017-10-01.
Detection: 2017-10-01 to 2018-01-02 (UTC). About 13 s.

- **Coverage:** 43,298 of 44,231 detection hours scored. The rest have no prediction: the model
  needs a usable scale, see D026.
- **Events:** 355 (185 high, 170 low), covering 5,147 hours, which is 11.9% of scored hours.
  Per meter, from 2 to 62 events (median 15); 19 of 20 meters have at least one.
  - Median duration 8 hours; 32 events last a day or more; 44 are kept as spikes.
  - 3 long events used the pre-event reference: Hog_parking_Marcus (480 h), Lamb_education_Lawrence
    (318 h) and Eagle_lodging_Andy (241 h).
- **Recognisable examples, as hypotheses to investigate, not verified causes:**
  - Gator buildings show whole-day low events starting at local midnight, on Sunday 1 October,
    on Friday 10 November (US Veterans Day observed) and on 30 December. Gator's region is
    unknown, so the model has no holiday information there (D025).
  - Lamb_education_Lawrence has a 318-hour low event with a peak score of 407. That looks like a
    meter or data fault rather than behaviour. Signature rules (T017) separate data faults.

**The alert volume is too high for operators, and the reason is measurable.**
- **Heavy tails:** even inside the calibration window, where the median and MAD come from, 3.0%
  of hours have |z| ≥ 4. A normal distribution would give 0.006%.
- **Seasonal drift:** in the winter detection quarter the share is 7.2%. A scale calibrated in
  summer is too narrow for winter.
- **Next steps:** threshold tuning against injected anomalies (T018), and calibrated intervals
  with seasonal or rolling calibration (T019). Until then, the event list is a candidate list
  for review, not an alert feed.

**Limits:** 20 meters, one quarter, untuned thresholds, and no ground truth for these events.
LEAD's labels cover 2016, which is inside this model's training period, so they cannot score
this detector without a model trained on other years (T018).
