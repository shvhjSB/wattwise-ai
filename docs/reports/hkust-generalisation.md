# HKUST: does the BDG2 model generalise to independent buildings? (T041)

**What this is:** the expected-consumption model trained on BDG2 (the promoted evaluation model,
D039), applied **without retraining** to the HKUST campus meters in Hong Kong, 2022–2024, and
compared with the baselines on the T010 chronological split with the T011 harness. It is
reported separately from every BDG2 result. Its numbers do not change the model, its card, or
any BDG2 figure.

**Data:** Li, Wang, Qu, Chui and Leung-Shea (2024), *A 2.5-year campus-level smart meter database
with equipment data for energy analytics*, Dryad,
[doi:10.5061/dryad.k3j9kd5h6](https://doi.org/10.5061/dryad.k3j9kd5h6), CC0 1.0. **Article:**
*A multi-year campus-level smart meter database*, Scientific Data (2024),
[doi:10.1038/s41597-024-04106-1](https://doi.org/10.1038/s41597-024-04106-1), read through Europe
PMC ([PMC11599614](https://europepmc.org/article/PMC/PMC11599614)). Obtained and
checksum-verified with `uv run python -m wattwise.data.dryad fetch hkust`
([manifest](../../data/manifests/hkust.json)); the files are git-ignored. Weather: ERA5 through
Open-Meteo ([manifest](../../data/manifests/hkust_era5.json)), CC BY 4.0, "Weather data by
Open-Meteo.com".

Reproduce: `python -m wattwise.data.hkust prepare`, `python -m wattwise.data.hkust
fetch-weather`, then `python -m wattwise.ml.hkust_eval --report
../docs/reports/hkust-generalisation.md` (about 19 minutes on the development machine).

## The question, fixed before the run

> On the HKUST test rows that both predict, does the BDG2 model (with ERA5 weather for the
> campus) have a lower MAE than seasonal-naive?

On BDG2's own test window the model was 18.0 % better than seasonal-naive, and 8.5 % better for
whole sites held out of training ([MODEL_CARD.md](../MODEL_CARD.md#evaluation)). The ERA5 variant
was named the primary one before the run, because it is closest to the inputs the model was
trained with; the no-weather variant is reported too.

## What was measured, documented, inferred and assumed

| Item | Status | Detail |
|---|---|---|
| Readings | **Observed:** cumulative registers in kWh | The article's meter table and the Brick metadata (`unit:KiloW-HR`). The clean files resample each meter to its own interval (15 or 30 minutes, an hour, or a day). Missing values "were neither imputed nor subjected to outlier detection" (article), so, unlike Building 59, nothing filled needs masking |
| Hourly consumption | **Derived** | Register at the next local hour boundary minus the register at this one. A negative difference (a reset or device restart, which the article mentions) or one above 10 × the meter's 99th percentile (the jump after a restart) is set missing, never filled: 46,088 and 1,518 hours, in 285 and 271 meters |
| Clock | **Inferred: Hong Kong time** (UTC+8, no daylight saving) | Not stated. The padding rows start at 1970-01-01 08:00, the Unix epoch in UTC+8; and campus consumption is lowest at 05:00 and rises from 06:00 on the parsed clock |
| Meters | **1,246 of 1,329 used** | 26 have daily data only, 56 read zero in every valid hour, 1 has no valid hour. 389 measure at 15 minutes, 620 at 30, 237 hourly. The article: of 1,412 meters, 1,268 measure devices, 121 rooms and the rest zones. Each meter is treated as its own unit; main meters and their sub-meters both appear (no double counting matters for per-meter forecasts) |
| Coverage | **Observed** | Median share of valid hours: 51 % (15-minute meters), 76 % (30-minute), 78 % (hourly), consistent with the article's missing rates. Per meter: [hkust-meters.csv](hkust-meters.csv) |
| Register resolution | **Observed** | The smallest positive hourly difference is at least 1 kWh for 398 meters, 10 kWh for 125 and 100 kWh for 14: coarse registers make hourly consumption lumpy for any forecaster |
| Weather | **Modelled substitute** | The dataset has none. ERA5 temperature, dew point and wind (a 0.25° grid cell) stand in for the station observations the model was trained with; radiation and cloud cover are ERA5 in both, as in BDG2 (T007d). Humidity is derived as in T007d |
| Holidays | **Reference** | Hong Kong public holidays (`holidays` package, region HK). Academic calendars are unknown |
| Split | **T010, chronological** | Local midnights: training 2022-01-01 to 2023-07-01 (only the hour-of-week profile is fitted on it), validation to 2023-10-01, test to 2024-05-28. The model is never refitted on HKUST |

## Findings

1. **Yes: the BDG2 model beats seasonal-naive on HKUST, by less than on BDG2.** On the 3.9
   million test rows every forecaster predicted (1,158 meters), MAE 4.977 kWh against 5.328
   (−6.6 %); on validation −5.5 %. That is a third of its margin on BDG2's own test window
   (−18.0 %) and a little below its margin on unseen BDG2 sites (−8.5 %): a model trained on
   North American and European campuses in 2016–2017 still helps on Hong Kong device and room
   meters in 2023–2024, but much of its advantage does not travel.

2. **Most meters improve.** On each meter's test rows both predicted, the model has the lower MAE
   on 872 of 1,160 meters (75 %). Every metered class and every interval improves at the median
   (−3.4 % to −13.2 %), most for equipment, lighting and elevators.

3. **Weather adds little here.** Without any weather input the model is still 5.5 % better than
   seasonal-naive on test, against 6.6 % with ERA5. Whether observed weather would add more is
   not tested: Hong Kong station data was not acquired.

4. **An 18-month-old profile is the worst baseline.** The hour-of-week median learned on
   2022–mid-2023 is 29.6 % worse than seasonal-naive on test (45.1 % on validation). The article
   describes the data as covering "one year of the COVID-19 pandemic and one year after lifting
   restrictions", so a fixed profile from the earlier period is a poor guide, while methods that
   use last week's readings adapt.

5. **Coverage is similar to seasonal-naive's.** On test, 989,972 rows with a reading have no
   model prediction (the model needs a usable last-week mean, at least 0.01 kWh), against
   933,301 for seasonal-naive (it needs the reading one week earlier). Over every row each
   scored, the model's MAE is 4.608 against 4.716.

## What this does not show

- It is one campus, in one region, with mostly device-level meters; it is not a result for
  buildings in general, and it does not validate the model's 90 % interval or the detector on
  HKUST (neither was run here).
- ERA5 is a modelled substitute for observed weather, and ERA5 values are for a grid cell, not
  the campus.
- The model was not retrained or tuned on HKUST; a model fitted to HKUST might do better, which
  is a different question.
- Sub-meters and their main meters are both scored, so the meters are not independent of each
  other.
- Nothing here changes a BDG2 result, and nothing is promoted.

<!-- generated: python -m wattwise.ml.hkust_eval -->

## Results (generated by `python -m wattwise.ml.hkust_eval`)

- **Model:** `20261027T121334Z-eeec81e9592c` (BDG2 evaluation model), not retrained.
- **Meters:** 1,246 of 1,329 used; not used: every valid hour is zero (56), daily data only (T1440) (26), no valid hourly consumption (1). 17,419,328 hourly readings.
- **Question (fixed before the run):** BDG2 model (ERA5 weather) MAE lower than seasonal-naive on common test rows. **Answer: yes** (change -6.6%; on BDG2's own test window -18.0%, unseen BDG2 sites -8.5%).

### Test window, rows every forecaster predicted (3,896,520 rows, 1,158 meters)

| Forecaster | MAE (kWh) | RMSE | Bias | WAPE | MAE vs seasonal-naive |
|---|---|---|---|---|---|
| seasonal-naive | 5.328 | 27.245 | 0.051 | 18.1% | +0.0% |
| hour-of-week-median | 6.908 | 31.124 | -0.294 | 23.5% | +29.6% |
| bdg2-model-era5-weather | 4.977 | 23.079 | 0.105 | 17.0% | -6.6% |
| bdg2-model-no-weather | 5.037 | 22.872 | -0.491 | 17.2% | -5.5% |

### Validation window, rows every forecaster predicted (1,361,880 rows, 1,107 meters)

| Forecaster | MAE (kWh) | RMSE | Bias | WAPE | MAE vs seasonal-naive |
|---|---|---|---|---|---|
| seasonal-naive | 6.355 | 31.661 | -0.099 | 17.2% | +0.0% |
| hour-of-week-median | 9.219 | 37.461 | -4.177 | 25.0% | +45.1% |
| bdg2-model-era5-weather | 6.003 | 26.426 | 0.583 | 16.3% | -5.5% |
| bdg2-model-no-weather | 6.220 | 26.956 | -0.976 | 16.9% | -2.1% |

### Coverage: every row each forecaster scored (test window)

| Forecaster | Rows scored | Rows with a reading but no prediction | MAE | WAPE | Macro MAE (per meter) | Meters |
|---|---|---|---|---|---|---|
| seasonal-naive | 4,484,534 | 933,301 | 4.716 | 18.2% | 3.542 | 1,222 |
| hour-of-week-median | 5,411,578 | 6,257 | 5.453 | 24.1% | 4.679 | 1,221 |
| bdg2-model-era5-weather | 4,427,863 | 989,972 | 4.608 | 17.2% | 3.538 | 1,161 |
| bdg2-model-no-weather | 4,427,863 | 989,972 | 4.662 | 17.4% | 3.577 | 1,161 |

### Per meter (test rows both predicted): the model has the lower MAE on 872 of 1,160 meters

| Group | Meters | Model better | Median MAE change |
|---|---|---|---|
| tier: T15 | 374 | 259 | -5.6% |
| tier: T30 | 561 | 433 | -9.4% |
| tier: T60 | 225 | 180 | -8.5% |
| metered: Elevator | 99 | 90 | -10.6% |
| metered: Equipment | 54 | 53 | -13.2% |
| metered: Lighting | 127 | 107 | -11.0% |
| metered: Riser | 75 | 57 | -6.5% |
| metered: Room | 142 | 99 | -7.9% |
| metered: Switch | 30 | 26 | -7.2% |
| metered: Water_Pump | 34 | 25 | -8.9% |
| metered: other | 210 | 123 | -3.4% |
| metered: unknown | 389 | 292 | -6.6% |

Per-meter coverage and errors: [hkust-meters.csv](hkust-meters.csv).
