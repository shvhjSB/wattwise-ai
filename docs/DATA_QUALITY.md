# WattWise AI — Data quality

**Quality version: `1`** · Source of truth:
[`backend/src/wattwise/data/quality.py`](../backend/src/wattwise/data/quality.py). A test fails if
this document stops naming every check and threshold.

The [data contract](DATA_CONTRACT.md) rejects data that is **structurally** broken: wrong types,
naive timestamps, unknown units, duplicate keys. The quality engine runs **after** the contract.
It **describes** valid data and flags where readings may be unreliable, without rejecting
anything.

Three rules shape every finding:

1. **Findings describe the data, not building behaviour.** A data-quality finding is not an
   anomaly and not a confirmed fault. Anomaly detection (M6) models expected behaviour; these
   checks only ask whether readings look like trustworthy measurements.
2. **Causes are hypotheses.** Messages say what is *possible* or *likely* (e.g. "a stuck meter
   or logger fault is likely; treat these readings as unreliable until checked"), never what
   happened.
3. **Behaviour is not flagged as bad data.** On the synthetic sample, the checks find exactly
   the two injected *data* faults (missing data, flatline) and none of the four injected
   *behaviour* anomalies (spike, sustained excess, overnight base load, drift). A test enforces
   this.

## Checks

Severity is either **info** (a fact worth knowing) or **warning** (the data is likely
unreliable here; check before use). Each meter is assessed on its own inferred interval: the
most common step between its timestamps.

| Check | Severity | What it finds | Threshold |
|---|---|---|---|
| `gaps` | info | Intervals with no row between a meter's first and last reading, reported with the longest gap | — |
| `irregular_interval` | warning | Steps between readings that are not a multiple of the meter's interval (shifted or mixed timestamps) | — |
| `missing_values` | info | Rows whose `value` is empty, reported with the longest run | — |
| `low_coverage` | warning | Available values as a share of expected intervals fall below the threshold | `min_coverage_pct` |
| `negative_values` | warning | Negative readings on a meter type that cannot measure them; solar is exempt, because export may be negative | — |
| `zero_runs` | warning | Runs of consecutive zero readings at least the threshold long (outage, disconnected meter, logger fault, or a real shutdown) | `zero_run_min_intervals` |
| `flatlines` | warning | Runs of consecutive identical **non-zero** readings at least the threshold long (stuck meter or logger fault). A gap breaks a run | `flatline_min_intervals`, `flatline_tolerance` |
| `extreme_values` | warning | Readings above a multiple of the meter's own 99th percentile (magnitude errors such as a Wh/kWh slip or a counter reset). Needs at least 100 readings | `extreme_ratio_to_p99` |
| `implausible_intensity` | warning | Electricity intensity (mean reading, annualised, per m² of floor area) outside a plausible range, suggesting a unit or scaling error, a wrong floor area, or a shared meter. Needs `buildings` with `floor_area_m2` | `min_intensity_kwh_m2_year`, `max_intensity_kwh_m2_year` |

Duplicate timestamps are a **contract** error (`duplicate_key`). When they occur, the quality
report lists them as contract issues and does not assess the data.

## Thresholds

All thresholds can be configured through `QualityThresholds`. The defaults:

| Threshold | Default | Rationale |
|---|---|---|
| `min_coverage_pct` | 95 | Below about 95%, baselines and benchmarks for a meter rest on visibly incomplete data. The check fires on *strictly* lower coverage |
| `flatline_min_intervals` | 6 | Six identical hourly readings from a live meter are very unlikely by chance. The synthetic stuck-meter event (12 h) is found, while short legitimate plateaus are not |
| `flatline_tolerance` | 0 | Identical means exactly equal. Raise it for meters that report rounded values |
| `zero_run_min_intervals` | 24 | Matches BDG2's own cleaning rule, which removed "zero readings longer than 24 continuous hours" ([DATASETS.md](DATASETS.md)) |
| `extreme_ratio_to_p99` | 5 | A reading more than 5× the meter's 99th percentile is far outside any normal peak. See the note below |
| `min_intensity_kwh_m2_year` | 2 | Deliberately wide. These bounds catch order-of-magnitude problems, not unusual buildings |
| `max_intensity_kwh_m2_year` | 2000 | Covers energy-intensive buildings such as laboratories and data rooms. A Wh-as-kWh slip lands far above it |

**Why `extreme_values` uses a ratio and not a z-score.** The first version used a robust z-score
(distance from the median in units of 1.4826 × MAD, threshold 10). On the synthetic sample it
flagged the injected 2.2× **behaviour** spike in `syn-office-a` at 11.3 robust SDs. Office load
is bimodal (occupied around 110 kWh, unoccupied around 45 kWh), which makes the MAD small. A
ratio to the 99th percentile is insensitive to that shape: the spike is about 2.1× the 99th
percentile (128.8), while a ×1000 unit slip stands out regardless.

## Reports

`assess(readings, buildings=None, thresholds=None)` returns a `QualityReport` with:

- **Fields:** `valid`, `contract_issues`, `thresholds`, `summary` and one `MeterQuality` per meter.
- **Per meter:**
  - `interval_minutes`, `first`, `last`
  - `expected_intervals`, `present_rows`, `absent_intervals`, `missing_values`, `available_values`
  - `coverage_pct`, `negative_values`, `zero_values`
- **Findings:** each has a `check`, `severity`, `message`, `count`, and an example window
  `start`–`end` (UTC, inclusive).
- **Summary:** totals, overall coverage, `meters_with_warnings` and `meters_by_check`.

Reports are rendered as JSON (`to_json`) and Markdown (`to_markdown`). Both are deterministic:
the same input always gives the same bytes, and no generation time is written.

From `backend/`:

```bash
uv run python -m wattwise.data.quality \
    --readings ../data/sample/synthetic/readings.csv \
    --buildings ../data/sample/synthetic/buildings.csv \
    --output-dir ../docs/reports --name synthetic-data-quality \
    --title "synthetic sample (data/sample/synthetic)"
```

The command exits with 1 if the input fails the contract. The committed example,
[`docs/reports/synthetic-data-quality.md`](reports/synthetic-data-quality.md) (and `.json`), is
kept up to date by a test.

## Limitations

- **Readings only.** Weather coverage is assessed when weather is joined to readings (T009).
- **Partial-period scaling errors may go undetected.** A meter recorded at the wrong scale for
  *part* of its history may pass both `implausible_intensity` (an annual mean) and
  `extreme_values` (if more than about 1% of readings are affected, the 99th percentile itself
  rises). Level-shift detection belongs to anomaly detection (T016–T017).
- **The interval is inferred per meter.** A meter with only one reading has no interval, and its
  coverage is trivially 100%.
- **Coverage runs from each meter's first to its last reading.** Missing data before the first
  or after the last reading is not counted.
