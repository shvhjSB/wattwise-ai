# T054 results: can the default detector find more human-labelled anomalies?

**Date:** 2026-11-02 · **Decision:** D072 · **Protocol:**
[t054-detector-protocol.md](t054-detector-protocol.md), committed and pushed as `f58fa6f`
**before** any candidate was scored.

**Real data, human labels without measured agreement (LEAD 1.0).** Labels are one annotator's
judgement, not ground truth. Only aggregates are published; LEAD stays local (D022).

## Result

**No setting met the predeclared criteria, so the default detector stays unchanged.**

- On the held-out window, the setting chosen on development found 1.8 points more labelled
  segments, with fewer alerts and higher event precision.
- That gain is below the predeclared minimum of 3 points, and its 95 % interval includes zero.
  It is a lead worth confirming, not an improvement.
- **The main reason for the low recall is not the short-event rule.** In the development window,
  864 of the 877 missed 1–2 hour segments (98.5 %) never reached |z| = 4. They are within the
  meter's normal same-hour variability, so no setting of this detector finds them without
  raising many more alerts.

## Why short segments are missed (development window, default setting)

Of 958 labelled 1–2 hour segments, the default missed 877. The largest |z| inside each missed
segment:

| Largest \|z\| in the segment | Missed segments | What stopped it |
|---|---|---|
| No score | 2 | Missing reading, or less than 7 days of history |
| **Below 4** | **864 (98.5 %)** | No event opened: the deviation was within 4 standard deviations of the same hour's recent level |
| 4 to 8 | 11 (1.3 %) | An event opened but was dropped: fewer than 3 hours reached z = 2 and the peak stayed below 8 |
| 8 or more | 0 | — |

- 645 of the missed segments were above the baseline and 230 below; 2 had no score.
- None had a zero reading.
- LEAD has no anomaly types, so results by type cannot be given. Direction above or below the
  baseline is the only split available.

The hypothesis written before the study was that the short-event rule (`min_hours = 3`,
`z_spike = 8`) drops short anomalies. It explains only 1.3 % of the misses.

## Development window (1 July to 1 October 2016, 173 meters, 1,316 segments)

Sorted by segment recall. Budget: 0.5 events per meter-week. **Bold** marks the settings within
the budget.

| Setting | Segment recall | 1–2 h | 3–23 h | 24 h+ | Events per meter-week | Event precision | Hour precision | Hour recall |
|---|---|---|---|---|---|---|---|---|
| median-on3-spike3 | 41.2 % | 25.4 % | 82.4 % | 88.9 % | 5.13 | 5.8 % | 5.0 % | 43.5 % |
| median-on4-spike4 | 36.8 % | 22.1 % | 74.6 % | 82.5 % | 3.75 | 7.0 % | 5.5 % | 38.3 % |
| median-on3-spike6 | 35.7 % | 23.1 % | 66.1 % | 85.7 % | 3.35 | 7.5 % | 5.2 % | 41.5 % |
| median-on3-spike8 | 34.2 % | 22.8 % | 60.3 % | 85.7 % | 3.12 | 7.7 % | 5.2 % | 41.0 % |
| median-on4-spike6 | 33.7 % | 20.8 % | 65.8 % | 80.9 % | 2.88 | 8.2 % | 5.7 % | 37.2 % |
| median-on5-spike5 | 32.6 % | 18.9 % | 68.1 % | 74.6 % | 2.92 | 8.0 % | 6.2 % | 35.5 % |
| median-on4-spike8 | 31.9 % | 20.3 % | 59.3 % | 80.9 % | 2.62 | 8.4 % | 5.7 % | 36.6 % |
| median-on5-spike6 | 31.8 % | 18.8 % | 64.7 % | 74.6 % | 2.55 | 8.8 % | 6.4 % | 35.1 % |
| median-on5-spike8 | 29.9 % | 18.3 % | 58.3 % | 74.6 % | 2.28 | 9.2 % | 6.4 % | 34.6 % |
| mean-on3-spike3 | 23.6 % | 12.5 % | 53.2 % | 52.4 % | 1.39 | 11.3 % | 9.7 % | 17.5 % |
| mean-on4-spike4 | 19.8 % | 9.9 % | 46.4 % | 44.4 % | 0.74 | 18.7 % | 14.0 % | 14.2 % |
| mean-on3-spike6 | 18.3 % | 10.9 % | 36.3 % | 47.6 % | 0.80 | 15.4 % | 10.3 % | 16.0 % |
| mean-on3-spike8 | 16.6 % | 10.5 % | 30.5 % | 44.4 % | 0.73 | 14.8 % | 10.1 % | 15.5 % |
| mean-on5-spike5 | 16.6 % | 8.4 % | 39.0 % | 36.5 % | 0.52 | 24.3 % | 16.7 % | 12.1 % |
| mean-on4-spike6 | 16.3 % | 8.8 % | 35.2 % | 41.3 % | 0.55 | 21.5 % | 14.3 % | 13.3 % |
| **mean-on5-spike6 (selected)** | **15.1 %** | 8.0 % | 33.6 % | 36.5 % | **0.45** | 26.1 % | 16.9 % | 11.8 % |
| **mean-on4-spike8 (default)** | **14.4 %** | 8.5 % | 28.8 % | 38.1 % | **0.48** | 21.2 % | 14.1 % | 12.8 % |
| **mean-on5-spike8** | **13.2 %** | 7.7 % | 26.8 % | 33.3 % | **0.38** | 26.8 % | 16.8 % | 11.3 % |

- The robust median baseline finds two to three times as many segments, but raises **2.3 to 5.1
  events per meter-week** (4.6 to 10 times the budget), and only 6 to 9 % of its events touch a
  label.
- Only three settings stay within the budget, and they differ by less than 2 points of recall.

## Held-out window (1 October 2016 to 2 January 2017, scored once, 773 segments)

| | Default (mean-on4-spike8) | Selected (mean-on5-spike6) | Change |
|---|---|---|---|
| Segment recall | 26.4 % | 28.2 % | +1.8 points |
| 1–2 h (507 segments) | 21.7 % | 22.1 % | +0.4 |
| 3–23 h (241) | 35.7 % | 41.1 % | +5.4 |
| 24 h or more (25) | 32.0 % | 28.0 % | −4.0 (one segment) |
| Events per meter-week | 0.391 | 0.345 | −0.046 |
| Event precision | 24.1 % | 30.7 % | +6.6 |
| Hour precision / recall | 9.0 % / 15.5 % | 12.2 % / 14.7 % | +3.2 / −0.8 |
| Chance hour precision | 1.0 % | 1.0 % | |

**Predeclared criteria:**

| Criterion | Result | Met |
|---|---|---|
| Segment recall at least 3 points above the default's | +1.8 points | **No** |
| Bootstrap 95 % interval of the gain above zero (meters resampled, 2,000 times) | −0.1 to +3.8 points | **No** |
| At most 0.5 events per meter-week | 0.345 | Yes |
| Event precision at most 2 points below the default's | +6.6 points | Yes |
| No duration band more than 5 points below the default's | Worst: −4.0 points (24 h or more) | Yes |

**Not promoted.** Because the LEAD criteria were not met, the injected-anomaly benchmark that
promotion would also have needed was not run.

Both settings found more of the labels in the held-out window (26–28 %) than in development
(14–15 %), and more than over July–December as a whole (18.9 %, T044c). The windows differ in
labels and season; the cause was not investigated.

## Detection delay (development window only, descriptive)

Delay is the hours from a found segment's first labelled hour to the start of the first event
overlapping it (0 if an event was already open). It was computed after the held-out run, on the
development window only, so the held-out window stays scored once.

| | Default | Selected |
|---|---|---|
| Segments found | 190 | 199 |
| Flagged from the first labelled hour | 55.8 % | 44.7 % |
| Median delay: 1–2 h / 3–23 h / 24 h or more | 0 / 1 / 6.5 h | 0 / 1 / 10 h |
| 90th percentile: 1–2 h / 3–23 h / 24 h or more | 1 / 2.6 / 19.7 h | 1 / 3.2 / 20.8 h |

The higher opening threshold of the selected setting finds long events later.

## What this means

- **Within the alert budget, this detector family cannot find most of LEAD's short labels.**
  They do not stand out from the meter's own recent same-hour readings. Lowering thresholds or
  using robust statistics finds more of them, but only with many times the alerts and mostly
  false ones.
- **Hypotheses for later work (not tested here):**
  - The annotator may have seen context the readings alone do not show, such as weather, other
    meters or schedules.
  - Some short labels may be judgement calls that a second annotator would not repeat;
    agreement is unmeasured.
  - An expectation that explains more of the normal variation (weather, occupancy) could
    shrink the scale enough to expose these deviations. The model detector found more segments
    in T044c, but at 3 times the budget.
- **A product question, not a technical one:** the 0.5 alerts per meter-week budget is an
  assumption the owner can change (D030). Every candidate's numbers at a higher budget are in
  the development table above, so any change can be judged with evidence. Any new budget must
  again be fixed before a fresh held-out test.
- **mean-on5-spike6** was better on held-out in recall, alerts and precision, but by less than
  the predeclared margin. A confirmation would need new labelled data or a new pre-registered
  test, not a second look at this window.

## Reproduce (local data only)

```bash
cd backend
uv run python -m wattwise.ml.detector_study development --data ../data/processed/bdg2/raw \
    --labels ../data/processed/lead/labels.parquet
uv run python -m wattwise.ml.detector_study held-out --data ../data/processed/bdg2/raw \
    --labels ../data/processed/lead/labels.parquet   # refuses to run twice
```

Local outputs, git-ignored, in `data/processed/evaluation/detector_study/`:

| File | SHA-256 |
|---|---|
| `development.json` | `83b2671aed156f5ad4554c0049217be87a4fdd545054119574486a7ee60a18fb` |
| `held_out.json` | `9f21151a164f325aeecda49e132dd8a4c7410c2acf7b16f915da7429626f53d3` |

The development phase took 5 min 44 s on the development machine.
