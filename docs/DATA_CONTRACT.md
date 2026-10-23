# WattWise AI — Data contract

**Contract version: `1.0`** · Source of truth:
[`backend/src/wattwise/data/contracts.py`](../backend/src/wattwise/data/contracts.py) and
[`validation.py`](../backend/src/wattwise/data/validation.py). A test fails if this document
stops naming every column and issue code that the code defines.

This contract is the one internal shape of energy data in WattWise AI. Everything uses it:
- synthetic fixtures (T006)
- dataset adapters such as BDG2 (T007/T009)
- data-quality checks (T008)
- models
- the upload API (T026)

## Principles

1. **Structure, not quality.** The contract rejects data that is malformed or physically
   impossible, such as an unknown unit, a latitude of 91° or two readings for one meter at one
   time. It does **not** judge plausibility. Gaps, negative electricity use, flatlined meters and
   outliers are data-quality findings, reported without rejecting the data
   ([DATA_QUALITY.md](DATA_QUALITY.md)).
2. **Time is UTC and explicit.** Every timestamp states its offset and is stored in UTC. A
   reading's `timestamp` is the **start** of its measurement interval. The interval length is
   inferred per meter from consecutive timestamps (T008); it is not a contract field.
3. **One canonical unit per meter type.** Adapters convert source units, e.g. kBTU to kWh,
   *before* data enters a canonical table. Validation never converts silently. It rejects values
   in a non-canonical unit.
4. **Missing is not zero.** A missing `value` means "not measured" and stays missing. It is never
   filled with 0.
5. **Every problem is reported once, actionably.** Each issue has a stable code, the affected
   rows, examples of the offending values and a hint on how to fix it.

## Tables

Column types:
- **identifier**: see [Identifiers](#identifiers).
- **timestamp**: timezone-aware, stored as `datetime64[us, UTC]`.
- **category**: a value from a fixed vocabulary.
- **number**: stored as `float64`; finite.
- **text**: free text.
- **timezone**: an IANA zone name.

"Required" means the column must be present. "Missing allowed" means individual cells may be empty.

### `readings`: one row per meter per interval

Primary key: (`meter_id`, `timestamp`).

| Column | Type | Required | Missing allowed | Unit | Meaning |
|---|---|---|---|---|---|
| `timestamp` | timestamp | yes | no | — | Start of the measurement interval, in UTC |
| `meter_id` | identifier | yes | no | — | Meter identifier, unique across buildings |
| `building_id` | identifier | yes | no | — | Building the meter belongs to |
| `meter_type` | category | yes | no | — | Kind of meter (see [Meter types](#meter-types-and-units)) |
| `unit` | category | yes | no | — | Unit of `value`; must be the meter type's canonical unit |
| `value` | number | yes | **yes** | see `unit` | Quantity consumed during the interval; empty = not measured |

These rules hold across rows:
- A meter belongs to exactly one building, with one meter type and one unit.
- Each (`meter_id`, `timestamp`) pair appears at most once.

### `buildings`: one row per building

Primary key: (`building_id`).

| Column | Type | Required | Missing allowed | Unit | Meaning |
|---|---|---|---|---|---|
| `building_id` | identifier | yes | no | — | Building identifier |
| `site_id` | identifier | yes | no | — | Site (campus) the building belongs to |
| `timezone` | timezone | yes | no | — | IANA time zone, e.g. `Europe/London`, for local calendar features |
| `primary_use` | text | no | yes | — | Primary space usage as given by the source |
| `floor_area_m2` | number | no | yes | m² | Gross floor area; must be > 0 |
| `latitude` | number | no | yes | degrees | WGS84 latitude, within [-90, 90] |
| `longitude` | number | no | yes | degrees | WGS84 longitude, within [-180, 180] |

Optional columns that are absent are added as all-missing in the canonical table. Location
fields are never inferred or invented.

### `weather`: one row per site per timestamp

Primary key: (`site_id`, `timestamp`).

| Column | Type | Required | Missing allowed | Unit | Meaning |
|---|---|---|---|---|---|
| `site_id` | identifier | yes | no | — | Site the observation applies to |
| `timestamp` | timestamp | yes | no | — | Observation time, in UTC |
| `air_temperature_c` | number | yes | yes | °C | Dry-bulb air temperature |
| `dew_temperature_c` | number | no | yes | °C | Dew-point temperature |
| `wind_speed_m_s` | number | no | yes | m/s | Wind speed; must be ≥ 0 |

## Meter types and units

The meter types follow the Building Data Genome Project 2 meter files. The canonical units are
WattWise's choice; source data is converted to them by adapters.

| `meter_type` | Canonical `unit` | Analysed in this version |
|---|---|---|
| `electricity` | `kWh` | **yes** |
| `chilledwater` | `kWh` | no |
| `steam` | `kWh` | no |
| `hotwater` | `kWh` | no |
| `gas` | `kWh` | no |
| `solar` | `kWh` | no |
| `water` | `m3` | no |
| `irrigation` | `m3` | no |

The units are `kWh` (energy, or energy equivalent) and `m3` (volume). Readings of types not
analysed yet satisfy the contract, but they raise an `unsupported_meter_type` warning and are
excluded from forecasting and anomaly detection. They are never mixed into electricity models.

## Identifiers

`meter_id`, `building_id` and `site_id` are 1–128 characters long:
- They start with a letter or digit.
- They then contain only letters, digits, `_`, `.`, `:` or `-`.
- No spaces, no commas, no accented letters.

Examples: `b1`, `office-1:electricity`, `Panther_parking_Lorriane`. The restriction keeps
identifiers safe in URLs, file names and log lines.

## CSV upload format

Readings can be uploaded as CSV. The `buildings` and `weather` tables follow the same rules
with their own columns.

- **Encoding:** UTF-8. A byte-order mark is allowed.
- **Delimiter:** comma. Quote values that contain commas, quotes or line breaks with double quotes.
- **Header:** the first row names the columns. Order does not matter; surrounding spaces are
  ignored. Extra columns cause an `unexpected_column` warning and are dropped.
- **Field count:** every row has exactly one field per header column. Blank lines are skipped.
- **Timestamps:** ISO 8601 with an explicit offset: `2016-01-01T00:00:00Z`,
  `2016-01-01T01:00:00+01:00` or `2016-01-01 01:00:00+0100`. A timestamp **without** an offset is
  rejected, never assumed to be UTC.
- **Numbers:** `.` as the decimal separator, no thousands separators. `1e3` is allowed.
- **Missing values:** an empty cell. Text such as `NaN`, `null` or `-` is rejected, not
  interpreted.
- **Row numbers in messages** count data rows: row 1 is the first row after the header.
  Structural CSV errors also give the file line.

A valid file:

```csv
timestamp,meter_id,building_id,meter_type,unit,value
2016-01-01T00:00:00Z,office-1:electricity,office-1,electricity,kWh,41.2
2016-01-01T01:00:00Z,office-1:electricity,office-1,electricity,kWh,
2016-01-01T03:00:00+01:00,office-1:electricity,office-1,electricity,kWh,39.8
```

The second reading is missing, which is allowed. The third timestamp is stored as
`2016-01-01T02:00:00Z`.

A file with mistakes:

```csv
timestamp,meter_id,building_id,meter_type,unit,value
2016-01-01T00:00:00Z,office-1:electricity,office-1,electricity,kWh,41.2
2016-01-01 01:00:00,office-1:electricity,office-1,electricity,kWh,39.8
2016-01-01T02:00:00Z,office-1:electricity,office-1,electricity,kwh,"1,204"
2016-01-01T00:00:00Z,office-1:electricity,office-1,electricity,kWh,40.0
```

The file is rejected. These are the exact messages the validator returns for it, captured from
a real run:

```text
[naive_timestamp] Column 'timestamp': 1 value has no time zone (row 2): '2016-01-01 01:00:00'. Timestamps must state their offset, e.g. 2016-01-01T00:00:00Z or 2016-01-01T01:00:00+01:00; they are stored in UTC.
[unknown_unit] Column 'unit': 1 value is not in the allowed vocabulary (row 3): 'kwh'. Allowed: kWh, m3. Did you mean: 'kwh' -> 'kWh'?
[non_numeric_value] Column 'value': 1 value is not a number (row 3): '1,204'. Use '.' as the decimal separator, no thousands separators, and leave the cell empty for a missing value.
[duplicate_key] 2 rows share their (meter_id, timestamp) with another row (rows 1, 4), e.g. office-1:electricity @ 2016-01-01 00:00:00+00:00. The key must be unique.
```

Each issue is also available as structured data:
- `code`, `severity` and `column`
- `message`
- `count`: the number of affected rows
- `rows`: up to 5 row numbers
- `examples`: up to 5 offending values

## Issue codes

**Errors** make a table invalid; **warnings** do not.

| Code | Severity | Meaning | How to fix |
|---|---|---|---|
| `empty_table` | error | The table or file has no data rows | Provide at least one data row |
| `missing_column` | error | A required column is absent | Add the column; the message lists the expected columns |
| `unexpected_column` | warning | A column is not in the contract | None needed; it is ignored |
| `duplicate_column` | error | A column name appears twice | Remove or rename the duplicate |
| `malformed_csv` | error | Broken CSV structure: unnamed header column, wrong field count or bad quoting | Give every row one field per column; quote values containing commas |
| `invalid_encoding` | error | The file is not UTF-8 | Save the file as UTF-8 CSV |
| `invalid_dtype` | error | A column holds the wrong kind of data (in-memory tables), e.g. integer identifiers | Convert the column, e.g. `.astype(str)` |
| `missing_value` | error | A column that needs a value has an empty cell | Fill the cell or drop the row |
| `invalid_identifier` | error | An identifier breaks the [identifier rules](#identifiers) | Use letters, digits, `_ . : -` only |
| `invalid_timestamp` | error | A timestamp is not valid ISO 8601 | Use e.g. `2016-01-01T00:00:00Z` |
| `naive_timestamp` | error | A timestamp has no time zone | Add an offset such as `Z` or `+01:00` |
| `unknown_meter_type` | error | `meter_type` is not in the vocabulary | Use one of the [meter types](#meter-types-and-units); the message suggests near matches |
| `unknown_unit` | error | `unit` is not in the vocabulary | Use `kWh` or `m3`; the message suggests near matches |
| `non_canonical_unit` | error | The unit is not the canonical one for the meter type | Convert values to the canonical unit before loading |
| `non_numeric_value` | error | A number column holds text | Use `.` decimals, no thousands separators, an empty cell for missing |
| `non_finite_value` | error | A number is infinite | Leave the cell empty if the value is unknown |
| `out_of_range` | error | A value is physically impossible, e.g. latitude 91 or floor area 0 | Correct the value |
| `invalid_timezone` | error | Not an IANA time zone name | Use e.g. `Europe/London`, `America/New_York` |
| `duplicate_key` | error | Two rows share a primary key | Keep one reading per meter and timestamp |
| `inconsistent_meter` | error | A meter appears with more than one building, type or unit | Fix the meter's metadata so every row agrees |
| `unsupported_meter_type` | warning | Valid readings of a type not analysed yet | None needed; they are excluded from analysis |

## Using the contract in code

```python
from wattwise.data.contracts import READINGS
from wattwise.data.csv_io import read_csv
from wattwise.data.validation import to_canonical, validate

report = validate(frame, READINGS)        # never modifies `frame`
if not report.ok:
    for issue in report.errors:
        print(issue.code, issue.message)

canonical = to_canonical(frame, READINGS) # raises ContractViolationError(report) if invalid

result = read_csv("readings.csv", READINGS)   # also accepts text or binary streams
if result.report.ok:
    canonical = result.frame
```

The canonical table has:
- exactly the contract's columns, in contract order
- canonical dtypes: `datetime64[us, UTC]` timestamps, `float64` numbers, `str` text
- rows sorted by the primary key

## Versioning

The contract version follows `MAJOR.MINOR`:
- **Major:** a change that can make previously valid data invalid, such as a new required
  column, a removed unit or a stricter rule.
- **Minor:** an additive change, such as a new optional column, a new meter type or a new warning.

Every change is recorded in [DECISIONS.md](DECISIONS.md) and the [CHANGELOG](../CHANGELOG.md).
