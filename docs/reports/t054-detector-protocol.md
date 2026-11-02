# T054 protocol: improving real-world anomaly detection (pre-registered)

**Written:** 2026-11-02, **before** any candidate was scored on the LEAD labels. The protocol is
committed and pushed before the development phase runs, so the selection rule and the acceptance
criteria cannot be changed after the results are seen. The code is
`backend/src/wattwise/ml/detector_study.py`; its constants are this protocol.

## Question

Can the default alert source, the rolling same-hour z-score (D030), find more of LEAD's
human-labelled anomaly segments without exceeding the alert budget?

Starting point, from the stored full-scale check (T044c,
`data/processed/fullscale-downstream/lead-scale/lead_check.json`, July to December 2016):

| | Value |
|---|---|
| Labelled meters | 173 |
| Labelled segments | 2,089 (median 1 hour) |
| **Segment recall, overall** | **18.86 %** |
| Recall on 1–2 h segments (1,465, 70 % of segments) | 13.04 % |
| Recall on 3–23 h segments (536) | 31.90 % |
| Recall on segments of 24 h or more (88) | 36.36 % |
| Events per meter-week | 0.431 |
| Event precision (events on a labelled anomaly, of judged events) | 22.66 % |

Labels are one annotator's judgement; agreement between annotators has never been measured, so
none of this is ground truth (D022).

## Why short segments may be missed (hypothesis, from the code)

An event opens when |z| reaches 4. It is then kept only if at least 3 hours reach |z| ≥ 2, or its
peak reaches 8 (`min_hours = 3`, `z_spike = 8`, `detection.py:_close`). A 1–2 hour anomaly is
therefore kept only if it is an extreme spike. A second possible cause: the 14-day mean and
standard deviation include earlier anomalies, which can inflate the scale and mask later ones.
The study tests both, and reports how the missed short segments break down by peak |z|.

## Data

- **Labels:** LEAD 1.0, trusted rows only (the LEAD reading equals BDG2's raw reading, D022).
  LEAD stays local; only aggregate results are published, never per-meter results.
- **Readings:** BDG2's raw variant for the labelled meters, from 1 June 2016 (history for the
  14-day window) to 2 January 2017.
- **No model:** only model-free settings are compared, so nothing is trained.

## Windows (chronological)

| Window | Dates (UTC) | Use |
|---|---|---|
| History | 1 June to 30 June 2016 | Readings only, for the rolling window |
| **Development** | 1 July to 1 October 2016 | Scoring all candidates and selecting one |
| **Held-out** | 1 October 2016 to 2 January 2017 | The default and the selected candidate, **scored once** |

The held-out window is strictly later than development. Readings before a window serve only as
the detector's past; no labels from the held-out window are read before the held-out run.
`python -m wattwise.ml.detector_study held-out` refuses to run a second time.

## Candidates (18, fixed now)

Every combination of:

- **Baseline statistic:** the mean and standard deviation of the same hour on the previous 14 days
  (the default), or the **median and MAD** (×1.4826) of the same values. The median version is
  robust to earlier anomalies in the window.
- **Opening threshold `z_on`:** 3, 4 (the default) or 5.
- **Short-event rule `z_spike`:** an event with fewer than 3 flagged hours is kept if its peak
  reaches `z_spike`: equal to `z_on` (every opened event is kept), 6, or 8 (the default).

Everything else stays at the default: `z_off = 2`, `min_hours = 3`, `max_gap_hours = 2`, no
pre-event reference, the 1 % scale floor, 14 days with at least 7.

**Not included, and why:**

- Model-based detectors: at full scale the model detector produced 1.47 events per meter-week,
  three times the budget (T044c).
- Change-point and multi-resolution methods: segments of 24 h or more are 4 % of the labels, so
  they cannot move the overall recall much. They are not justified as a first step.
- Weather-adjusted baselines: the rolling baseline already follows the previous 14 days.
  Separating the weather effect is not part of this study.

## Metrics

The T018b scoring rules (`lead_check.score`), unchanged:

- **Segment recall:** a labelled run of consecutive anomaly hours counts as found if any event
  overlaps it. Reported overall and for 1–2 h, 3–23 h and 24 h or more.
- **Hour precision and recall.**
- **Event precision:** events overlapping a labelled anomaly, among events judged on trusted hours.
- **Events per meter-week:** over the labelled meters in the window.

## Selection rule (development window only)

1. Keep the candidates with at most **0.5 events per meter-week** (the alert budget, D030; a
   product assumption the owner can change).
2. Choose the highest segment recall.
3. Ties within 0.001 go to fewer events per meter-week, then to the default.
4. If no candidate is within the budget, the default is chosen.

## Acceptance criteria (held-out window, all required)

1. Segment recall at least **0.03 above the default's**.
2. A meter-clustered, paired bootstrap 95 % interval of that difference (2,000 resamples,
   seed 0) entirely **above zero**.
3. At most **0.5 events per meter-week**.
4. Event precision no more than **0.02 below the default's**.
5. No duration band (1–2 h, 3–23 h, 24 h or more) with recall more than **0.05 below the
   default's**.

If every criterion is met, the candidate **qualifies for promotion**. Promotion then also requires
the injected-anomaly benchmark (the T044b harness) run with the candidate:

- its injected recall must be no more than 0.05 below the default's;
- at no more than 0.5 alerts per meter-week.

Promotion changes the default for every new detection, the stored alerts and the demo, so it is
its own reviewed change after this study. If any criterion fails, **the default stays**, and the
report explains the result from the diagnostics. Both improvements and regressions are reported.
