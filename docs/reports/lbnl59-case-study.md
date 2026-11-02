# LBNL Building 59: a one-building detector case study (T040)

**What this is:** WattWise's default detector run on one real, sub-metered office building, with
its alerts compared against the building's end uses, rooftop-unit (RTU) dampers, outdoor
temperature, measured occupancy and the authors' own timeline of events. **One building's case
study.** It says nothing about the causes of any alert in BDG2 buildings, and no result here is a
performance claim for other buildings.

**Data:** LBNL Building 59 (Wang Hall), Berkeley, California, 2018–2020. Hong, Luo, Blum and
Wang (2022), *A three-year building operational performance dataset for informing energy
efficiency*, Dryad, [doi:10.7941/D1N33Q](https://doi.org/10.7941/D1N33Q) (version 162054), CC0
1.0. **Article:** Luo, Wang, Blum, Weyandt, Bourassa, Piette and Hong (2022), *A three-year
dataset supporting research on building energy management and occupancy analytics*, Scientific
Data 9:156, [doi:10.1038/s41597-022-01257-x](https://doi.org/10.1038/s41597-022-01257-x), read
through Europe PMC's open-access copy ([PMC8983728](https://europepmc.org/article/PMC/PMC8983728)).
Obtained and checksum-verified with `uv run python -m wattwise.data.dryad fetch lbnl59`
([manifest](../../data/manifests/lbnl59.json)); the files are git-ignored. Regenerate the results
with `uv run python -m wattwise.ml.lbnl59 --report ../docs/reports/lbnl59-case-study.md`.

## What was measured, documented, inferred and assumed

| Item | Status | Detail |
|---|---|---|
| Electricity (`ele.csv`, kW, 15-minute) | **Observed**, after the authors' gap filling | Five panel meters (article, Table 3): south and north plug loads (`mels_S`, `mels_N`), south office lighting (`lig_S`), and the two HVAC panels (`hvac_S`, `hvac_N`), each serving two RTUs "as well as the building elevators" |
| The series analysed | **Derived:** the sum of the five | The article: "No record for the lighting electricity in the north wing." Common areas, special rooms and emergency power are on other panels of the office switchboard. So this is a sub-metered total, not the building's bill. North lighting is not estimated (the authors note the wings are similar, but filling it in would be invented data) |
| Clock of the energy, weather, RTU and occupancy files | **Inferred: UTC** | The article and files do not state it. Three checks on the data: solar radiation peaks near 20:30 (solar noon in Berkeley is about 20:15 UTC); the energy file has no daylight-saving gap or repeat; the morning lighting ramp moves one clock hour between January and July, as it does for people keeping daylight-saving time. The Wi-Fi file behaves like local time and is not used (its counts are zero until April 2020) |
| Imputed values | **Rule documented; linear fills identified, others not** | Article, Table 4, for `ele.csv`: gaps "<10 hours: Linear, 10 hours to 1 day: KNN, >1 day: MF". A linear fill puts the filled points on one sloped straight line between two real points; those interior points are masked when the run has at least 5 points (a gap of 45 minutes or more). Shorter runs happen by chance at the 0.1 kW resolution of 2018–2019: on 2020 data rounded to 0.1 kW, chance runs cover up to 13.6 % of points at 3 points, 1.2 % at 4, and at most 0.13 % at 5. Constant runs are kept (lights off at night are flat). KNN and matrix-factorisation fills leave no trace, and no raw data is published (Dryad has one version; the linked catalogue points back to it), so the "unknown imputed share" in the results remains |
| Dated events | **Documented by the authors** | Article, Table 2 "Key timeline of events": wildfire 2018-11-12 to 11-20; shelter-in-place 2020-03-18 to 12-31; wildfire 2020-08-24 to 09-06; MPC testing 2020-10-20 to 10-27, 11-02 to 11-06, 11-13 to 11-19 and 12-04 to 12-14. The article: "In about three weeks during 2018 and 2020, the building closed the outdoor air dampers to minimize outdoor air flow rate due to air pollution caused by the wildfires." |
| Damper closures in the data | **Observed** | Weekdays with every RTU's outdoor-air damper at its 10 % minimum for at least 6 of the 9 working hours. A check on the authors' dates, and a reminder that closures happen for other reasons too |
| Occupancy (`occ.csv`) | **Observed**, 2018-05-22 to 2019-02-21 only | Camera-based counts for two half-floors. None of the largest events falls in that period |

## Findings

1. **The data changes character between years, and the article does not explain it.** South
   HVAC fell from about 28 kW to 4 kW in December 2018; north plug loads stepped from about 11 to
   4 kW in the first week of January 2020, before COVID; and the share of values recorded with
   at most two decimals collapsed at the same boundaries (`mels_N`: 75 % in 2018, 0 % in 2020).
   Together these suggest changes in metering or data processing, not only in the building.
   Linear fills are found in 2018–2019 and almost none in 2020 (at most 0.05 % of points). Any comparison across years in this
   building, including the 2018–2019 hour-of-week profile below, mostly measures these shifts.

2. **The default detector did not flag the start of shelter-in-place.** Weekly mean load went
   from 49.2 kW (week from 3 March) to 39.6, 31.4, 29.0 and 27.0 kW (week from 1 April), down
   45 %, across the authors' start date of 18 March. The decline was spread over three weeks, and
   the rolling same-hour baseline (the previous 14 days) followed it, so no event marks it. This
   is the expected behaviour of a 14-day rolling baseline (D030), now seen on real data:
   **gradual or stepwise regime changes are not what this detector finds.** They are visible in
   weekly means and in the profile's error, not in the alerts.

3. **The wildfire damper closures are in the data, and the detector does not see them.** In both
   of the authors' wildfire windows the dampers were far more closed than in the two weeks before
   (working-hours mean 22.4 % against 49.8 % in November 2018, and 12.6 % against 37.1 % in
   August–September 2020). No detector event overlaps either window: closing the dampers left no
   detectable mark on the electricity total. The data also shows closures the timeline does not
   list: on 2018-11-09, three days before the authors' first window, and on 2020-09-10 to 09-15,
   after their second ends (the Bay Area Air District's smoke alerts ran "through Friday,
   September 11",
   [source](https://www.baaqmd.gov/News-and-Events/Page-Resources/2020-News/090920-STA)). Most
   other closures fall on days much hotter (for example 32.7 °C against 18.8 °C in June 2019) or
   colder than the weeks before, which fits ordinary economiser control. **A damper at its
   minimum is therefore not, by itself, evidence of smoke**; the authors' timeline is.

4. **MPC tests: HVAC was lower in all four windows, and the detector flagged one.** Mean HVAC
   power during the authors' MPC windows was 15–56 % below the 14 days before (for example 15.6
   against 32.5 kW for 4 to 14 December). The comparison is not adjusted for weather, and some
   "before" periods contain an earlier MPC window. The detector raised one event, a low
   sustained event on 4–6 December, almost entirely south HVAC (−818 of −840 kWh). The other
   three windows produced none: their reductions were either gradual enough, or close enough to
   recent variation, for the 14-day baseline.

5. **Where the detector fires, the end-use breakdown localises it.** All events decompose exactly
   into the five end uses (arithmetic: the total is their sum, and the baseline is a mean). In
   the ten largest, HVAC carries almost all of the deviation. That says *where* the deviation was
   metered, not *why*. The largest (21–22 October 2019, both HVAC wings, about +1,500 kWh above
   the rolling baseline) is in no dated window; it is an anomaly to investigate, not confirmed
   waste, and its cause is unknown.

6. **Baselines.** Against 2020, the hour-of-week profile learned on 2018–2019 is biased high in
   every month (WAPE 38–136 %) because of finding 1. The detector's own rolling baseline tracks
   the building much more closely (WAPE 13–37 %). Neither number is a forecasting result for
   other buildings.

## What this does not show

- It does not validate the detector: there are no labelled anomalies here, and the dated events
  are context, not ground truth for every hour.
- It does not establish causes. Signatures name patterns, and the end-use breakdown is
  attribution by arithmetic. The MPC and wildfire comparisons are before/after means without a
  weather adjustment.
- KNN and matrix-factorisation fills remain in the data (at least the "unknown imputed share"
  below) and cannot be told apart from measurements.
- Nothing about BDG2 buildings follows from it.

<!-- generated: python -m wattwise.ml.lbnl59 -->

## Results (generated by `python -m wattwise.ml.lbnl59`)

- **Series:** sum of the five metered end uses mels_S, lig_S, mels_N, hvac_N, hvac_S (kW, hourly mean = kWh); derived, not a whole-building meter.
- **Period (local):** 2017-12-31 17:00 to 2020-12-31 15:00; 16,886 of 26,304 hours used (9,418 masked or missing).
- **Detector:** `rolling-z` with its default thresholds.

### Masking: suspected interpolation against the authors' raw missing rates

| End use | Raw missing rate (authors) | Masked as suspected interpolation | Unknown imputed share left (at least) |
|---|---|---|---|
| `mels_S` | 32.9% | 20.2% | 12.7% |
| `lig_S` | 18.2% | 8.4% | 9.8% |
| `mels_N` | 19.7% | 10.8% | 8.9% |
| `hvac_N` | 8.1% | 2.1% | 6.1% |
| `hvac_S` | 8.1% | 1.7% | 6.4% |

### Level of each end use by year (mean kW over used hours)

Share of the year's clean-file values with at most two decimals in brackets: a change in it marks a change in how values were recorded or processed.

| Year | Hours used | `mels_S` | `lig_S` | `mels_N` | `hvac_N` | `hvac_S` |
|---|---|---|---|---|---|---|
| 2017 | 7 | 1.2 (93%) | 0.2 (100%) | 7.2 (93%) | 37.5 (68%) | 20.7 (100%) |
| 2018 | 4,816 | 3.4 (75%) | 1.6 (83%) | 12.1 (75%) | 35.7 (68%) | 21.9 (69%) |
| 2019 | 3,304 | 3.2 (54%) | 1.8 (67%) | 11.6 (46%) | 18.2 (20%) | 12.2 (33%) |
| 2020 | 8,759 | 1.0 (40%) | 0.7 (65%) | 2.3 (0%) | 9.4 (24%) | 25.7 (22%) |

### Baselines scored on each month of 2020

The profile learned 2018-2019; the rolling mean is the detector's own baseline (the same hour on the previous 14 days).

| Month | Hours | Profile MAE (kWh) | Profile WAPE | Profile bias (kWh) | Rolling MAE (kWh) | Rolling WAPE |
|---|---|---|---|---|---|---|
| 2020-01 | 742 | 27.1 | 67% | 27.1 | 9.7 | 24% |
| 2020-02 | 696 | 22.0 | 49% | 21.9 | 9.9 | 22% |
| 2020-03 | 743 | 28.5 | 74% | 28.5 | 9.0 | 23% |
| 2020-04 | 720 | 30.8 | 84% | 30.8 | 5.7 | 15% |
| 2020-05 | 743 | 26.0 | 64% | 25.8 | 7.0 | 17% |
| 2020-06 | 720 | 28.8 | 74% | 28.7 | 8.2 | 21% |
| 2020-07 | 744 | 28.2 | 72% | 28.1 | 4.9 | 13% |
| 2020-08 | 744 | 18.9 | 38% | 17.5 | 8.1 | 17% |
| 2020-09 | 706 | 24.3 | 56% | 24.0 | 9.0 | 21% |
| 2020-10 | 744 | 28.8 | 74% | 28.0 | 14.3 | 37% |
| 2020-11 | 721 | 37.7 | 129% | 37.7 | 9.1 | 31% |
| 2020-12 | 736 | 38.9 | 136% | 38.9 | 10.5 | 37% |

### Weeks around the start of shelter-in-place

Seven-day windows from the authors' start date, 2020-03-18 (local).

| Week from | Mean kW | Hours |
|---|---|---|
| 2020-02-18 | 48.0 | 168 |
| 2020-02-25 | 51.7 | 168 |
| 2020-03-03 | 49.2 | 168 |
| 2020-03-11 | 39.6 | 168 |
| 2020-03-18 | 31.4 | 168 |
| 2020-03-25 | 29.0 | 168 |
| 2020-04-01 | 27.0 | 168 |
| 2020-04-08 | 37.4 | 168 |

### Events: 38 in total, 33 outside the wildfire, MPC and damper windows

| Signature (direction) | Events |
|---|---|
| overnight_excess (high) | 7 |
| spike (high) | 2 |
| spike (low) | 4 |
| sustained (high) | 4 |
| sustained (low) | 1 |
| unclassified (high) | 7 |
| unclassified (low) | 13 |

### Dated windows and the events that overlap them

Authors' windows are the article's Table 2 (https://europepmc.org/article/PMC/PMC8983728); damper windows are weekdays with every RTU damper at its 10 % minimum, found in the data. Damper % and outdoor °C are working-hours means (08:00-17:00 local), HVAC kW an all-hours mean, each in the window and in the 14 days before it. A window longer than a month lists only its event count.

| Window (local dates) | Basis | Damper % | Outdoor °C | HVAC kW | Overlapping events |
|---|---|---|---|---|---|
| wildfire 2018-11-12 to 2018-11-20 | authors' timeline | 22.4 / 49.8 | 14.7 / 18.5 | 61.6 / 59.2 | none |
| shelter-in-place 2020-03-18 to 2020-12-31 | authors' timeline | 42.3 / 44.9 | 18.0 / 12.7 | 35.2 / 36.2 | 17 events |
| wildfire 2020-08-24 to 2020-09-06 | authors' timeline | 12.6 / 37.1 | 19.4 / 24.9 | 41.8 / 50.6 | none |
| MPC testing 2020-10-20 to 2020-10-27 | authors' timeline | 64.0 / 33.9 | 19.1 / 22.8 | 17.5 / 39.8 | none |
| MPC testing 2020-11-02 to 2020-11-06 | authors' timeline | 58.2 / 59.1 | 19.4 / 19.7 | 21.8 / 25.5 | none |
| MPC testing 2020-11-13 to 2020-11-19 | authors' timeline | 52.2 / 48.9 | 14.5 / 16.6 | 16.5 / 29.2 | none |
| MPC testing 2020-12-04 to 2020-12-14 | authors' timeline | 52.8 / 44.5 | 14.1 / 14.2 | 15.6 / 32.5 | low sustained, 2020-12-04 11:00 to 2020-12-06 01:00, -839.7 kWh (`hvac_S` -818.0) |
| damper-at-minimum 2018-11-09 to 2018-11-09 | found in the RTU data | 10.0 / 59.4 | 17.1 / 18.9 | 46.6 / 63.2 | none |
| damper-at-minimum 2018-11-13 to 2018-11-13 (in an authors' wildfire window) | found in the RTU data | 10.0 / 47.3 | 15.4 / 18.5 | 56.9 / 59.2 | none |
| damper-at-minimum 2018-11-19 to 2018-11-19 (in an authors' wildfire window) | found in the RTU data | 10.0 / 31.0 | 14.8 / 16.1 | no data | none |
| damper-at-minimum 2018-12-05 to 2018-12-05 | found in the RTU data | 10.3 / 39.7 | 9.0 / 12.1 | 33.5 / 45.6 | none |
| damper-at-minimum 2019-02-04 to 2019-02-04 | found in the RTU data | 10.4 / 39.5 | 6.9 / 12.8 | 29.7 / 41.0 | none |
| damper-at-minimum 2019-06-10 to 2019-06-11 | found in the RTU data | 10.0 / 55.3 | 32.7 / 18.8 | 89.8 / 35.7 | none |
| damper-at-minimum 2019-08-14 to 2019-08-15 | found in the RTU data | 12.5 / 55.2 | 30.0 / 20.8 | 93.8 / 46.7 | none |
| damper-at-minimum 2019-09-12 to 2019-09-13 | found in the RTU data | 15.0 / 52.3 | 29.2 / 21.0 | 88.9 / 49.5 | none |
| damper-at-minimum 2019-09-24 to 2019-09-25 | found in the RTU data | 10.8 / 46.1 | 30.6 / 22.4 | 72.5 / 57.8 | none |
| damper-at-minimum 2020-04-24 to 2020-04-24 | found in the RTU data | 31.8 / 48.6 | 23.0 / 15.2 | 46.0 / 35.6 | none |
| damper-at-minimum 2020-05-07 to 2020-05-08 | found in the RTU data | 23.7 / 52.9 | 24.4 / 18.9 | 47.1 / 39.8 | none |
| damper-at-minimum 2020-05-25 to 2020-05-27 | found in the RTU data | 10.1 / 56.5 | 27.0 / 16.9 | 54.4 / 35.8 | high sustained, 2020-05-24 11:00 to 2020-05-25 21:00, 553.8 kWh (`hvac_S` 551.4); high sustained, 2020-05-26 01:00 to 2020-05-27 14:00, 810.3 kWh (`hvac_S` 771.0) |
| damper-at-minimum 2020-06-02 to 2020-06-04 | found in the RTU data | 15.6 / 45.8 | 26.4 / 19.9 | 47.9 / 40.0 | none |
| damper-at-minimum 2020-06-09 to 2020-06-11 | found in the RTU data | 26.4 / 40.8 | 22.6 / 20.3 | 44.3 / 37.7 | none |
| damper-at-minimum 2020-06-17 to 2020-06-18 | found in the RTU data | 17.6 / 42.8 | 24.8 / 19.7 | 48.0 / 35.8 | none |
| damper-at-minimum 2020-08-03 to 2020-08-03 | found in the RTU data | 21.0 / 58.3 | 23.5 / 17.3 | 45.9 / 35.8 | high unclassified, 2020-08-03 10:00 to 2020-08-03 20:00, 181.2 kWh (`hvac_S` 188.9) |
| damper-at-minimum 2020-08-28 to 2020-09-04 (in an authors' wildfire window) | found in the RTU data | 13.5 / 25.5 | 16.6 / 24.4 | 39.6 / 53.6 | none |
| damper-at-minimum 2020-09-10 to 2020-09-15 | found in the RTU data | 10.2 / 14.8 | 18.8 / 20.7 | 45.7 / 37.9 | none |
| damper-at-minimum 2020-10-01 to 2020-10-02 | found in the RTU data | 10.0 / 51.5 | 29.8 / 23.0 | 61.4 / 41.5 | high unclassified, 2020-09-30 23:00 to 2020-10-01 15:00, 357.8 kWh (`hvac_S` 351.0) |

### The ten largest events by absolute deviation

| Start to end (local) | Direction, signature | Deviation (kWh) | By end use (kWh) | Damper % (event / before) | Occupants (event / before) |
|---|---|---|---|---|---|
| 2019-10-21 11:00 to 2019-10-22 17:00 | high, sustained | 1,498.4 | mels_S 56.7, lig_S 42.0, mels_N 78.6, hvac_N 683.6, hvac_S 637.4 | 41.7 / 42.0 | no data |
| 2019-10-24 15:00 to 2019-10-25 06:00 | high, unclassified | 845.7 | mels_S 6.4, lig_S 11.8, mels_N 30.9, hvac_N 386.9, hvac_S 409.6 | 33.4 / 39.8 | no data |
| 2020-12-04 11:00 to 2020-12-06 01:00 | low, sustained | -839.7 | mels_S -1.9, lig_S -7.2, mels_N -3.1, hvac_N -9.5, hvac_S -818.0 | 55.2 / 40.2 | no data |
| 2020-08-13 20:00 to 2020-08-15 10:00 | high, sustained | 828.9 | mels_S -2.1, lig_S -5.7, mels_N 25.8, hvac_N 0.4, hvac_S 810.4 | 43.0 / 45.8 | no data |
| 2020-05-26 01:00 to 2020-05-27 14:00 | high, sustained | 810.3 | mels_S 1.1, lig_S 7.0, mels_N 31.4, hvac_N -0.3, hvac_S 771.0 | 34.2 / 50.4 | no data |
| 2020-06-05 05:00 to 2020-06-06 00:00 | low, unclassified | -629.2 | mels_S -6.5, lig_S 0.5, mels_N -11.5, hvac_N 0.6, hvac_S -612.3 | 43.0 / 42.1 | no data |
| 2020-05-24 11:00 to 2020-05-25 21:00 | high, sustained | 553.8 | mels_S -3.0, lig_S -8.3, mels_N 21.4, hvac_N -7.8, hvac_S 551.4 | 39.1 / 52.1 | no data |
| 2020-06-27 21:00 to 2020-06-28 15:00 | low, unclassified | -403.7 | mels_S -1.4, lig_S -1.8, mels_N -2.7, hvac_N 4.8, hvac_S -402.6 | 41.7 / 50.8 | no data |
| 2019-10-23 07:00 to 2019-10-23 13:00 | high, unclassified | 363.0 | mels_S 4.3, lig_S 12.9, mels_N 47.6, hvac_N 160.2, hvac_S 138.0 | 52.3 / 41.8 | no data |
| 2020-09-30 23:00 to 2020-10-01 15:00 | high, unclassified | 357.8 | mels_S -0.1, lig_S 0.2, mels_N 12.3, hvac_N -5.6, hvac_S 351.0 | 10.0 / 55.7 | no data |
