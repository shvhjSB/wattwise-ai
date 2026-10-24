# Features

Feature set version: **1** · Module: `wattwise.ml.features` · Decision: D025 · Task: T013

The feature table gives every reading one row of model inputs. Models (T014) learn expected
consumption from it. A test keeps this document in sync with the code: each feature in the
table below must exist with this group, source and unit, and no other feature may exist.

```
uv run python -m wattwise.ml.features --data ../data/processed/bdg2/cleaned \
    --enrichment ../data/processed/era5/weather_enrichment.parquet
```

The command writes `features.parquet` (`timestamp`, `meter_id`, `building_id` plus the features)
and `manifest.json` to git-ignored `data/processed/features/`. The manifest holds the feature
set version, the horizon, the `holidays` version, the rules, each column's provenance, the input
and output hashes, and each feature's missing share. The same inputs give byte-identical files.

## Leakage rules

1. **Conditions** (calendar, holidays, weather, sun) describe the target interval or earlier
   intervals, never a later one.
2. **Consumption history** uses only readings whose interval started at least **H** hours
   before the target interval starts. H is the horizon: 1 to 168 hours, default 168. The
   default matches the seasonal-naive baseline (D024). The target reading, and everything after
   it, never enters its own features.
3. **Nothing is fitted.** No imputation, scaling or encoding is learned from data. Missing
   inputs stay NaN, and flag columns record what was available. The model fits imputation and
   scaling on training rows only (T014).

Tests prove rules 1 and 2. If every reading from a cutoff on is rewritten, no feature changes
before cutoff + H, and history features change from exactly cutoff + H. Changing weather after a
cutoff changes nothing up to the cutoff. A reading never changes its own row. The same check
on the real BDG2 sample (horizons 1, 24 and 168 h) also gave a first change at exactly cutoff + H.

**Why weather at the target hour is allowed.** WattWise models *expected* consumption under the
conditions that actually occurred: the counterfactual baseline that anomalies are measured
against. That needs the observed weather of the interval itself. It is not a weather forecast,
so a model that uses weather features measures **expected-consumption accuracy, not forecast
accuracy**. A true day-ahead forecast would need forecast weather, which is not in scope.

**History features and anomalies.** With H = 168, a sustained anomaly enters the history
features one week after it starts, and a model may then treat it as normal. T014 and T016 should
compare models with and without the `history` group (`FeatureConfig(groups=...)`).

## Feature list

Sources: **computed** from the timestamp and building metadata; **reference** from the
`holidays` package; **observed** BDG2 measurements; **derived** by a stated formula from observed
values; **modelled** ERA5 reanalysis, a grid-cell value, not a site measurement. Every feature
is a float64; NaN means not available. "as value" means the unit of the meter's readings (kWh
for electricity).

| Feature | Group | Source | Unit | Description |
|---|---|---|---|---|
| `hour_local` | calendar | computed | h | Hour of day, 0–23, in the building's local wall time |
| `day_of_week_local` | calendar | computed | - | 0 = Monday … 6 = Sunday, local |
| `is_weekend_local` | calendar | computed | 0/1 | Local Saturday or Sunday |
| `month_local` | calendar | computed | - | 1–12, local |
| `day_of_year_local` | calendar | computed | - | 1–366, local |
| `hour_sin` | calendar | computed | - | sin(2π · hour_local / 24) |
| `hour_cos` | calendar | computed | - | cos(2π · hour_local / 24) |
| `day_of_year_sin` | calendar | computed | - | sin(2π · (day_of_year_local − 1) / days in the year) |
| `day_of_year_cos` | calendar | computed | - | cos(2π · (day_of_year_local − 1) / days in the year) |
| `is_public_holiday` | holiday | reference | 0/1 | Public holiday on the local date in the site's country and region (observed days included); NaN if the region is unknown |
| `holiday_region_known` | holiday | computed | 0/1 | 1 if the site's country is known |
| `air_temperature_c` | weather | observed | degC | BDG2 air temperature at the interval start |
| `dew_temperature_c` | weather | observed | degC | BDG2 dew point at the interval start |
| `wind_speed_m_s` | weather | observed | m/s | BDG2 wind speed at the interval start |
| `relative_humidity_pct_derived` | weather | derived | % | Magnus formula from observed temperature and dew point (T007d) |
| `air_temperature_mean_24h_c` | weather | derived | degC | Mean observed temperature over the interval start and the 23 hours before; NaN with fewer than 12 observations |
| `heating_degrees_c` | weather | derived | degC | max(0, 18 − air_temperature_c) |
| `cooling_degrees_c` | weather | derived | degC | max(0, air_temperature_c − 18) |
| `ghi_w_m2_era5` | weather | modelled | W/m2 | ERA5 global horizontal irradiance, mean over the interval (T007d) |
| `cloud_cover_pct_era5` | weather | modelled | % | ERA5 total cloud cover at the interval start (T007d) |
| `weather_observed` | weather | computed | 0/1 | 1 if an air temperature was observed at the interval start |
| `era5_available` | weather | computed | 0/1 | 1 if ERA5 irradiance exists for the interval |
| `solar_elevation_deg` | sun | computed | deg | Geometric sun elevation at the middle of the interval; NaN without coordinates |
| `is_daylight` | sun | computed | 0/1 | 1 if solar_elevation_deg > 0; NaN without coordinates |
| `day_length_h` | sun | computed | h | Sunrise to sunset on the local date; NaN without coordinates |
| `lag_168h` | history | observed | as value | The meter's reading one week before the interval start |
| `lag_336h` | history | observed | as value | The meter's reading two weeks before |
| `same_hour_mean_4w` | history | derived | as value | Mean of the readings 1–4 weeks before; NaN with fewer than 2 of them |
| `rolling_mean_24h` | history | derived | as value | Mean over the 24 h ending H before the interval start; NaN with fewer than 12 readings |
| `rolling_mean_168h` | history | derived | as value | Mean over the 168 h ending H before; NaN with fewer than 84 readings |
| `rolling_std_168h` | history | derived | as value | Sample standard deviation over the same window |
| `rolling_min_168h` | history | derived | as value | Minimum over the same window: a baseload indicator |

The lags and the four-week mean are at least one week back, so they satisfy rule 2 for every
allowed horizon. The rolling windows move with H.

## Alignment and inputs

- **Readings:** timestamps are UTC interval starts (D016). Feature set 1 needs whole-hour
  timestamps and refuses anything else, including duplicate meter-hours and readings of buildings
  missing from the buildings table.
- **Local calendar:** each reading is converted with its building's IANA zone, so hours stay
  aligned with occupancy across daylight-saving changes. The zones are the corrected metadata
  (Fox is `America/Phoenix`, D020).
- **Weather:** BDG2 observations are instants on the hour (D016), joined at the interval start.
  ERA5 irradiance is the mean over the interval (relabelled in T007d), and cloud cover is an
  instant at its start. Weather is joined by site and hour; nothing is interpolated or filled
  from another source.
- **Degree hours:** 18 °C is a common convention (about 65 °F), not a fitted balance point.
  Tree models do not need it; linear models can use it.

## Holidays

The `holidays` package 0.106 (MIT) supplies the calendars, with observed days (such as a Monday
after a holiday on a Sunday) included. Each site's country and region come from the T009c table
(`SITE_REGIONS`). A site without a known region gets NaN, never a guessed country: a "US/…"
zone name does not prove the country (D020). A public holiday is not a campus closure. No source
of academic calendars exists for the anonymised BDG2 campuses (D019), so term breaks are not
features.

## Sun position

`wattwise.data.solar` implements NOAA's General Solar Position Calculations, which T007d already
used for the equation of time. pvlib was planned, but the NOAA equations are enough: they were
cross-checked once against pvlib 0.16.1's NREL SPA over 2016–2017 at six test points. They agree
within 0.53° of elevation (mean 0.1–0.3°) and 5.2 minutes of day length, against a sun that moves
15° an hour. pvlib was not added as a dependency (D025).

## Results on the BDG2 sample

Pipeline version 2 sample: 20 meters at 9 sites, 350,816 readings, ERA5 enrichment included.

- **Build time:** 6.6 s in Python, and about 10 s for the command with file I/O. The same
  features come out whatever the row order (tested on the real data).
- **Missing shares:**

| Features | Missing | Why |
|---|---|---|
| Calendar | 0% | — |
| Holiday, sun, ERA5 radiation and cloud cover | 25.00% | Eagle (15% of rows) and Gator (10%) have no coordinates and no known region |
| Observed temperature / dew point / wind | 0.55% / 0.61% / 0.76% | Hours without a BDG2 observation |
| Derived humidity | 0.61% | Missing temperature or dew point |
| 24-hour temperature mean | 0.10% | Fewer than 12 observations in the window |
| History | 4.98–6.26% | The first weeks of each meter, and gaps in its readings |

These are input-availability numbers, not model results.
