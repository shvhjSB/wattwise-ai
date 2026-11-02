# LBNL Building 59: a one-building detector case study (T040)

**What this is:** WattWise's default detector run on one real, sub-metered office building, with
its alerts compared against the building's end uses, rooftop-unit (RTU) dampers, outdoor
temperature, measured occupancy and two dated events. **One building's case study.** It says
nothing about the causes of any alert in BDG2 buildings, and no result here is a performance
claim for other buildings.

**Data:** LBNL Building 59, Berkeley, California, 2018–2020. Hong, Luo, Blum and Wang (2022),
*A three-year building operational performance dataset for informing energy efficiency*, Dryad,
[doi:10.7941/D1N33Q](https://doi.org/10.7941/D1N33Q) (version 162054), CC0 1.0; article in
*Scientific Data*, [doi:10.1038/s41597-022-01257-x](https://doi.org/10.1038/s41597-022-01257-x).
Obtained and checksum-verified with `uv run python -m wattwise.data.dryad fetch lbnl59`
([manifest](../../data/manifests/lbnl59.json)); the files are git-ignored. Regenerate the results
with `uv run python -m wattwise.ml.lbnl59 --report ../docs/reports/lbnl59-case-study.md`.

## What was measured, inferred and assumed

| Item | Status | Detail |
|---|---|---|
| Electricity end uses (`ele.csv`, kW, 15-minute) | **Observed**, after the authors' gap filling | Five columns: south and north plug loads (`mels_S`, `mels_N`), south lighting (`lig_S`), south and north HVAC (`hvac_S`, `hvac_N`). Units and sampling from the authors' data-description table |
| Whole-building series | **Derived** | The sum of the five end uses. There is no north-wing lighting column and no whole-building meter in the files, so this is a sub-metered total, not the building's bill |
| Clock of `ele.csv`, weather, RTU and occupancy files | **Inferred: UTC** | Not documented. Solar radiation peaks near 20:30 (solar noon in Berkeley is about 20:15 UTC), the energy file has no daylight-saving gap or repeat, and the morning lighting ramp moves by one clock hour between January and July, as it would for people keeping daylight-saving time. The Wi-Fi file appears to use local time; it is not used (below) |
| Imputed values | **Partly identifiable** | The authors filled gaps (linear interpolation, KNN, matrix factorisation) and do not flag them. Runs of at least six points on one sloped straight line are masked as *suspected* interpolation; constant runs are kept, because lights off at night are genuinely flat. KNN and matrix-factorisation fills leave no trace, so at least the "unknown imputed share" in the results table remains in the data |
| Shelter-in-place date | **Sourced** | Berkeley Lab, 17 March 2020: "Six Bay Area counties have ordered all residents to shelter-in-place beginning March 17 and lasting until at least April 7. … This includes the Lab." ([source](https://elementsarchive.lbl.gov/2020/03/17/shelter-in-place-order-for-six-bay-area-counties/)) |
| Wildfire-smoke period | **Sourced, with one inference** | Bay Area Air District: smoke Spare the Air alerts for 18 and 19 August 2020 ([source](https://www.baaqmd.gov/News-and-Events/Page-Resources/2020-News/081820-STA)), extended "through Friday, September 11" as "the 24th and 25th consecutive" alert ([source](https://www.baaqmd.gov/News-and-Events/Page-Resources/2020-News/090920-STA)). That the run was unbroken from 18 August is inferred from that count |
| "Wildfire damper closures" | **Not documented anywhere checked** | Earlier project notes listed them as a dated event, without a source. Neither the dataset files nor the sources above mention dampers, and the article could not be read (its publisher pages redirect to a sign-in, and the PubMed Central copy answers with a CAPTCHA). Damper closures are therefore **found in the data** (every RTU's outdoor-air damper held at its 10 % minimum for at least 6 of the 9 working hours of a weekday), and any link to smoke is a hypothesis |
| Occupancy (`occ.csv`) | **Observed**, 2018-05-22 to 2019-02-21 only | Counts for two half-floors. No event in that period is among the largest, so occupancy shows "no data" for them |

## Findings

1. **The data changes character between years, and the change is not documented.** The table of
   yearly levels shows south HVAC falling from about 28 kW to 4 kW in December 2018, north plug
   loads stepping from about 11 to 4 kW in the first week of January 2020 (before COVID), and the
   share of values recorded with two decimals collapsing at the same boundaries (`mels_N`: 75 %
   in 2018, 0 % in 2020). Together these suggest changes in metering or data processing, not
   only in the building. Masking removes most of 2018–2019 (suspected interpolation) and nothing
   in 2020. Any comparison across years in this building, including the hour-of-week profile
   below, mostly measures these level shifts.

2. **The default detector did not flag the shelter-in-place drop.** The sourced order date falls
   inside a three-week decline: weekly mean load went from 50.5 kW (week from 2 March) to
   41.5, 33.5, 27.8 and 27.1 kW (week from 31 March), down 46 %. The rolling same-hour baseline
   (the previous 14 days) followed the gradual decline, so no event marks it. The two events
   that overlap the window are short and dominated by south HVAC. This is the expected
   behaviour of a 14-day rolling baseline (D030), and the case study confirms it on real data:
   **gradual or stepwise regime changes are not what this detector finds.** A regime change is
   visible in the weekly means and in the 2018–2019 profile's error, not in the alerts.

3. **The data cannot tell smoke closures from ordinary damper control, and the detector does
   not see the smoke-period closures.** Of 19 spans with every damper at minimum, 11 fall on
   days at least 3 °C warmer than the two weeks before (for example 32.7 °C against 18.8 °C in
   June 2019), which fits ordinary economiser control: minimum outdoor air when outside air is
   hot. Five more (November 2018 to February 2019) fall on cooler days, which also fits ordinary
   minimum-air operation in cold weather. Two spans fall inside the sourced smoke-alert period
   (28 August to 4 September and 10 to 15 September 2020), on days cooler than the days before
   (16.6 against 24.4 °C, and 18.8 against 20.7 °C). In late summer, when this building's other
   closures came on hot days, that is consistent with closures for smoke, but the cool-weather
   spans of 2018–19 show that a closure on a mild day is not by itself evidence of smoke, and
   the dataset does not document why any damper closed. **No detector event overlaps either
   smoke-period span**: whatever the reason, those closures left no detectable mark on the
   electricity total. Where an event does overlap a damper span (hot days in May, August and
   October 2020), it is a high event dominated by south HVAC, consistent with cooling load on a
   hot day.

4. **Where the detector does fire, the end-use breakdown localises it.** All 39 events are
   decomposed exactly into the five end uses (the breakdown is arithmetic, because the total is
   the sum of the end uses and the baseline is a mean). In the ten largest, HVAC carries almost
   all of the deviation; plug loads and lighting contribute little. That says *where* the
   deviation was metered, not *why*: for example, the largest event (21–22 October 2019, both
   HVAC wings, about +1,000 kWh above the rolling baseline) is an anomaly to investigate, not
   confirmed waste, and its cause is unknown.

5. **Baselines.** Against 2020, the hour-of-week profile learned on 2018–2019 is biased high in
   every month (WAPE 38–135 %) because of finding 1. The detector's own rolling baseline tracks
   the building much more closely (WAPE 13–37 %). Neither number is a forecasting result for
   other buildings.

## What this does not show

- It does not validate the detector: there are no labelled anomalies in this building, and the
  dated events are context, not ground truth.
- It does not establish any cause. Signatures name patterns; the damper-and-smoke link is a
  hypothesis; the end-use breakdown is attribution by arithmetic.
- It does not measure the effect of the masking choice: some imputed values (KNN, matrix
  factorisation) remain and cannot be told apart from measurements.
- Nothing about BDG2 buildings follows from it.

<!-- generated: python -m wattwise.ml.lbnl59 -->

## Results (generated by `python -m wattwise.ml.lbnl59`)

- **Series:** sum of the five metered end uses mels_S, lig_S, mels_N, hvac_N, hvac_S (kW, hourly mean = kWh); derived, not a whole-building meter.
- **Period (local):** 2017-12-31 17:00 to 2020-12-31 15:00; 17,517 of 26,304 hours used (8,787 masked or missing).
- **Detector:** `rolling-z` with its default thresholds.

### Masking: suspected interpolation against the authors' raw missing rates

| End use | Raw missing rate (authors) | Masked as suspected interpolation | Unknown imputed share left (at least) |
|---|---|---|---|
| `mels_S` | 32.9% | 21.3% | 11.6% |
| `lig_S` | 18.2% | 8.6% | 9.5% |
| `mels_N` | 19.7% | 11.3% | 8.4% |
| `hvac_N` | 8.1% | 2.2% | 5.9% |
| `hvac_S` | 8.1% | 1.8% | 6.3% |

### Level of each end use by year (mean kW over used hours)

Share of the year's clean-file values with at most two decimals in brackets: a change in it marks a change in how values were recorded or processed.

| Year | Hours used | `mels_S` | `lig_S` | `mels_N` | `hvac_N` | `hvac_S` |
|---|---|---|---|---|---|---|
| 2017 | 7 | 1.2 (93%) | 0.2 (100%) | 7.2 (93%) | 37.5 (68%) | 20.7 (100%) |
| 2018 | 5,178 | 3.4 (75%) | 1.6 (83%) | 12.2 (75%) | 35.5 (68%) | 21.9 (69%) |
| 2019 | 3,556 | 3.2 (54%) | 1.8 (67%) | 11.7 (46%) | 18.5 (20%) | 12.4 (33%) |
| 2020 | 8,776 | 1.0 (40%) | 0.7 (65%) | 2.3 (0%) | 9.4 (24%) | 25.7 (22%) |

### Baselines scored on each month of 2020

The profile learned 2018-2019; the rolling mean is the detector's own baseline (the same hour on the previous 14 days).

| Month | Hours | Profile MAE (kWh) | Profile WAPE | Profile bias (kWh) | Rolling MAE (kWh) | Rolling WAPE |
|---|---|---|---|---|---|---|
| 2020-01 | 744 | 27.1 | 67% | 27.1 | 9.7 | 24% |
| 2020-02 | 696 | 21.9 | 49% | 21.8 | 9.9 | 22% |
| 2020-03 | 743 | 28.5 | 74% | 28.4 | 9.0 | 23% |
| 2020-04 | 720 | 30.7 | 84% | 30.6 | 5.7 | 15% |
| 2020-05 | 744 | 25.9 | 63% | 25.7 | 6.9 | 17% |
| 2020-06 | 720 | 28.7 | 74% | 28.6 | 8.2 | 21% |
| 2020-07 | 744 | 28.1 | 71% | 28.0 | 4.9 | 13% |
| 2020-08 | 744 | 18.8 | 38% | 17.5 | 8.1 | 17% |
| 2020-09 | 720 | 24.3 | 56% | 24.0 | 9.0 | 21% |
| 2020-10 | 744 | 28.7 | 73% | 27.9 | 14.3 | 37% |
| 2020-11 | 721 | 37.7 | 129% | 37.7 | 9.1 | 31% |
| 2020-12 | 736 | 38.8 | 135% | 38.8 | 10.5 | 37% |

### Weeks around the shelter-in-place order (7-day windows from 2020-03-17, local)

| Week from | Mean kW | Hours |
|---|---|---|
| 2020-02-17 | 47.0 | 168 |
| 2020-02-24 | 51.4 | 168 |
| 2020-03-02 | 50.5 | 168 |
| 2020-03-10 | 41.5 | 168 |
| 2020-03-17 | 33.5 | 168 |
| 2020-03-24 | 27.8 | 168 |
| 2020-03-31 | 27.1 | 168 |
| 2020-04-07 | 35.5 | 168 |

### Events: 39 in total, 33 outside the dated windows

| Signature (direction) | Events |
|---|---|
| overnight_excess (high) | 7 |
| spike (high) | 2 |
| spike (low) | 4 |
| sustained (high) | 3 |
| sustained (low) | 1 |
| unclassified (high) | 8 |
| unclassified (low) | 14 |

### Dated windows and the events that overlap them

Smoke-alert period (sourced): 2020-08-18 to 2020-09-11. Outdoor temperature is the working-hours mean in the window and in the 14 days before it.

| Window (local dates) | Basis | In smoke-alert period | Outdoor °C (window / before) | Overlapping events | Largest deviation by end use |
|---|---|---|---|---|---|
| shelter-in-place 2020-03-17 to 2020-04-07 | sourced date |  | 11.3 / 13.5 | low unclassified, 2020-04-04 23:00 to 2020-04-05 09:00, -103.7 kWh | `hvac_S` -101.5 kWh |
| shelter-in-place 2020-03-17 to 2020-04-07 | sourced date |  | 11.3 / 13.5 | high overnight_excess, 2020-04-07 22:00 to 2020-04-08 07:00, 87.6 kWh | `hvac_S` 67.1 kWh |
| damper-at-minimum 2018-11-09 to 2018-11-09 | observed in the RTU data | no | 17.1 / 18.9 | none | |
| damper-at-minimum 2018-11-13 to 2018-11-13 | observed in the RTU data | no | 15.4 / 18.5 | none | |
| damper-at-minimum 2018-11-19 to 2018-11-19 | observed in the RTU data | no | 14.8 / 16.1 | none | |
| damper-at-minimum 2018-12-05 to 2018-12-05 | observed in the RTU data | no | 9.0 / 12.1 | none | |
| damper-at-minimum 2019-02-04 to 2019-02-04 | observed in the RTU data | no | 6.9 / 12.8 | none | |
| damper-at-minimum 2019-06-10 to 2019-06-11 | observed in the RTU data | no | 32.7 / 18.8 | none | |
| damper-at-minimum 2019-08-14 to 2019-08-15 | observed in the RTU data | no | 30.0 / 20.8 | none | |
| damper-at-minimum 2019-09-12 to 2019-09-13 | observed in the RTU data | no | 29.2 / 21.0 | none | |
| damper-at-minimum 2019-09-24 to 2019-09-25 | observed in the RTU data | no | 30.6 / 22.4 | none | |
| damper-at-minimum 2020-04-24 to 2020-04-24 | observed in the RTU data | no | 23.0 / 15.2 | none | |
| damper-at-minimum 2020-05-07 to 2020-05-08 | observed in the RTU data | no | 24.4 / 18.9 | none | |
| damper-at-minimum 2020-05-25 to 2020-05-27 | observed in the RTU data | no | 27.0 / 16.9 | high sustained, 2020-05-24 11:00 to 2020-05-25 21:00, 553.8 kWh | `hvac_S` 551.5 kWh |
| damper-at-minimum 2020-05-25 to 2020-05-27 | observed in the RTU data | no | 27.0 / 16.9 | high sustained, 2020-05-26 01:00 to 2020-05-27 14:00, 810.3 kWh | `hvac_S` 771.0 kWh |
| damper-at-minimum 2020-06-02 to 2020-06-04 | observed in the RTU data | no | 26.4 / 19.9 | none | |
| damper-at-minimum 2020-06-09 to 2020-06-11 | observed in the RTU data | no | 22.6 / 20.3 | none | |
| damper-at-minimum 2020-06-17 to 2020-06-18 | observed in the RTU data | no | 24.8 / 19.7 | none | |
| damper-at-minimum 2020-08-03 to 2020-08-03 | observed in the RTU data | no | 23.5 / 17.3 | high unclassified, 2020-08-03 10:00 to 2020-08-03 20:00, 181.2 kWh | `hvac_S` 188.9 kWh |
| damper-at-minimum 2020-08-28 to 2020-09-04 | observed in the RTU data | yes | 16.6 / 24.4 | none | |
| damper-at-minimum 2020-09-10 to 2020-09-15 | observed in the RTU data | yes | 18.8 / 20.7 | none | |
| damper-at-minimum 2020-10-01 to 2020-10-02 | observed in the RTU data | no | 29.8 / 23.0 | high unclassified, 2020-09-30 23:00 to 2020-10-01 15:00, 357.8 kWh | `hvac_S` 351.0 kWh |

### The ten largest events by absolute deviation

| Start to end (local) | Direction, signature | Deviation (kWh) | By end use (kWh) | Damper % (event / before) | Occupants (event / before) |
|---|---|---|---|---|---|
| 2019-10-21 11:00 to 2019-10-22 06:00 | high, unclassified | 1,047.2 | mels_S 29.5, lig_S 23.8, mels_N 33.0, hvac_N 495.4, hvac_S 465.4 | 41.2 / 42.6 | no data |
| 2020-12-04 11:00 to 2020-12-06 01:00 | low, sustained | -839.7 | mels_S -1.9, lig_S -7.2, mels_N -3.1, hvac_N -9.5, hvac_S -818.0 | 55.2 / 40.2 | no data |
| 2020-08-13 20:00 to 2020-08-15 10:00 | high, sustained | 828.9 | mels_S -2.1, lig_S -5.7, mels_N 25.8, hvac_N 0.4, hvac_S 810.4 | 43.0 / 45.8 | no data |
| 2020-05-26 01:00 to 2020-05-27 14:00 | high, sustained | 810.3 | mels_S 1.1, lig_S 7.0, mels_N 31.4, hvac_N -0.3, hvac_S 771.0 | 34.2 / 50.4 | no data |
| 2019-10-23 01:00 to 2019-10-23 13:00 | high, unclassified | 794.6 | mels_S 7.7, lig_S 15.0, mels_N 54.6, hvac_N 390.2, hvac_S 327.2 | 63.8 / 38.7 | no data |
| 2020-06-05 05:00 to 2020-06-06 00:00 | low, unclassified | -629.2 | mels_S -6.5, lig_S 0.5, mels_N -11.5, hvac_N 0.6, hvac_S -612.3 | 43.0 / 42.1 | no data |
| 2020-05-24 11:00 to 2020-05-25 21:00 | high, sustained | 553.8 | mels_S -3.0, lig_S -8.3, mels_N 21.4, hvac_N -7.8, hvac_S 551.5 | 39.1 / 52.1 | no data |
| 2019-09-27 17:00 to 2019-09-28 02:00 | low, unclassified | -492.1 | mels_S -2.4, lig_S -0.4, mels_N -2.6, hvac_N -237.6, hvac_S -249.1 | 44.6 / 55.2 | no data |
| 2019-10-22 09:00 to 2019-10-22 17:00 | high, unclassified | 451.1 | mels_S 27.7, lig_S 18.3, mels_N 45.7, hvac_N 184.9, hvac_S 174.5 | 24.3 / 41.9 | no data |
| 2020-06-27 21:00 to 2020-06-28 15:00 | low, unclassified | -403.7 | mels_S -1.4, lig_S -1.8, mels_N -2.7, hvac_N 4.8, hvac_S -402.6 | 41.7 / 50.8 | no data |
