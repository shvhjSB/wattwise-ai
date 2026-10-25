# Anomaly detection

Detector version: **1** · Signatures version: **1** · Modules: `wattwise.ml.detection`,
`wattwise.ml.signatures` · Decisions: D028, D029 · Tasks: T016, T017

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

## Signatures (T017)

Every event gets the signatures whose rules match, with the **evidence**: the measured values
next to the thresholds, as JSON in `events.csv`. The **primary** signature is the first match in
this order. Meter problems come first, so they are never presented as consumption:

| Signature | Rule (defaults) | Meaning |
|---|---|---|
| `data_fault` | Any negative reading; a run of at least 24 zero readings; at least 50% of hours missing; or a peak score of at least 50 | The readings look like a metering or data problem. Check the meter first |
| `flatline` | The same non-zero reading (tolerance 0) for at least 6 hours, covering at least 50% of the event | A stuck or not truly hourly meter. Check the meter first |
| `spike` | At most 3 hours | A short deviation |
| `overnight_excess` | A high event with at least 70% of its excess in local hours 22:00–05:59 | Excess at base-load time |
| `drift` | At least 72 hours, with the mean deviation rising across the event's thirds by at least 50% of the last third | A growing deviation |
| `sustained` | At least 24 hours, with at least 60% of hours flagged | A long deviation |
| `unclassified` | No rule matched | — |

- **Shared thresholds:** the flatline and zero-run lengths are the data-quality engine's (T008),
  so both describe a stuck meter the same way.
- **Evaluation:** thresholds are provisional; T018 evaluates them.
- **Wording:** signatures name patterns, never causes. Their descriptions are tested for causal
  words, and causes are hypotheses for T020.
- **Baseline:** rules run on the hours exactly as the detector saw them, including the pre-event
  baseline of long events.

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
- **Recognisable examples:**
  - **Gator's whole-day low events are a data issue.** In T016 these were first read as
    possible holidays. The T017 signatures label them `flatline`. On those days BDG2's raw file
    holds one value for every hour: 3.3333 or 8.3333 kWh, which is 80 or 200 kWh divided by 24.
    That is consistent with a daily total spread evenly over the day, a data-resolution
    problem rather than behaviour.
  - Lamb_education_Lawrence has a 318-hour low event with a peak score of 407, labelled
    `data_fault` (an implausible deviation).

**Signatures** (primary; high and low together):

| Signature | Events | Event hours |
|---|---|---|
| `data_fault` | 4 | 324 |
| `flatline` | 12 | 530 |
| `spike` | 80 | 175 |
| `overnight_excess` | 9 | 60 |
| `drift` | 0 | 0 |
| `sustained` | 19 | 1,822 |
| `unclassified` | 231 | 2,236 |

- **Meter problems:** 16 events (854 hours) are data faults or flatlines. They are meter
  problems to check, not consumption to act on.
- **All `data_fault` events** are implausible deviations: a peak z of 52–407 at Bull and Lamb
  meters.
- **Overnight excess:** 22 events match it in total; 9 have it as their primary signature.
- **No drift:** no long event's deviation grew steadily.
- **Unclassified: 65% of events.** Most last 4–23 hours: too long for a spike, too short for
  `sustained`, and not concentrated at night. They are reported as unclassified rather than
  forced into a pattern.

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
