# WattWise AI — Datasets

Which datasets WattWise uses, where they come from, how to obtain them, their licences, and the
conventions an adapter must respect. **No external dataset is committed to this repository.**
Raw downloads live under `data/raw/` and processed tables under `data/processed/`; both are
git-ignored. Only the small synthetic sample and provenance manifests are committed.

| Dataset | Role | In the repository? | How to obtain |
|---|---|---|---|
| Synthetic sample | Tests, demo mode, synthetic benchmarks | Yes: [`data/sample/synthetic/`](../data/sample/synthetic/README.md), about 564 KB | Generated: `uv run python -m wattwise.data.synthetic` |
| Building Data Genome Project 2 (BDG2) | Primary real data for forecasting and anomaly detection | **No.** Only the manifest [`data/manifests/bdg2.json`](../data/manifests/bdg2.json) | Explicit download, about 369 MB (below) |
| Supplementary data (labels, carbon, prices, weather, sub-metered buildings) | Evaluated, not yet acquired | No | See [Supplementary data](#supplementary-data-evaluation-t007b) |

## Building Data Genome Project 2 (BDG2)

### What it is

The BDG2 README and paper describe 3,053 energy meters from 1,636 non-residential buildings,
with hourly readings for 2016 and 2017. A subset was used in ASHRAE's Great Energy Predictor III
(GEPIII) Kaggle competition, so GEPIII data is **not** independent validation for BDG2. WattWise
uses electricity only for now (D012): 1,578 buildings have an electricity meter.

**Cite as** (metadata verified with Crossref):

> Miller, C., Kathirgamanathan, A., Picchetti, B. et al. The Building Data Genome Project 2,
> energy meter data from the ASHRAE Great Energy Predictor III competition. *Sci Data* **7**, 368
> (2020). https://doi.org/10.1038/s41597-020-00712-x

Also acknowledge the repository, https://github.com/buds-lab/building-data-genome-project-2,
and its Zenodo release, https://doi.org/10.5281/zenodo.3887306.

### Source and pin

| | |
|---|---|
| Repository | `buds-lab/building-data-genome-project-2` |
| Pinned commit | `753598e0a19400af950b1513e1daeb680658c1fd` (2020-06-24, "Correct weather.csv") |
| Why this commit | It is the last commit that changed any data file. Its data files are byte-identical to `master` (`9b97ccb`, 2023-10-14), verified by comparing the Git LFS pointers |
| Why not tag `v1.0` | `v1.0` (2020-06-04, the Zenodo deposit) predates two corrections: `electricity_cleaned.csv` was updated on 2020-06-15, and `weather.csv` was corrected on 2020-06-24 (a `weather_UTC.csv` was added on 06-23 and removed on 06-24) |
| Download endpoint | `https://media.githubusercontent.com/media/<repo>/<commit>/<path>` (Git LFS). `raw.githubusercontent.com` returns 131-byte LFS pointer files, not data |
| Integrity | Each file must match the size and SHA-256 recorded in its LFS pointer at the pinned commit |

| Key | File in the repository | Size (bytes) | SHA-256 |
|---|---|---|---|
| `metadata` | `data/metadata/metadata.csv` | 272,024 | `992d0b29…ecddca02` |
| `weather` | `data/weather/weather.csv` | 19,457,782 | `a8189f1c…44f04bd` |
| `electricity_raw` | `data/meters/raw/electricity.csv` | 174,239,039 | `039d909d…a66418` |
| `electricity_cleaned` | `data/meters/cleaned/electricity_cleaned.csv` | 174,977,911 | `b6ffc9b4…e6c630a3` |

The full hashes are in [`backend/src/wattwise/data/bdg2.py`](../backend/src/wattwise/data/bdg2.py)
and the manifest.

### Download and verify

From `backend/`:

```bash
uv run python -m wattwise.data.bdg2 list      # files, sizes, checksums; no network
uv run python -m wattwise.data.bdg2 fetch     # explicit download into ../data/raw/bdg2 (~369 MB)
uv run python -m wattwise.data.bdg2 verify    # offline re-check of local copies
```

- **Verification:** a file is only saved after its size and SHA-256 match. Downloads go to a
  `.part` file first, and nothing partial is ever left behind.
- **Re-runs:** files that are already verified are not downloaded again.
- **No silent overwrites:** an existing file that does not match is never overwritten; `--force`
  replaces it explicitly. `--only metadata weather` fetches a subset.
- **Provenance:** `fetch` records the commit, URLs, sizes, checksums, download and verification
  times, the citation and the licence evidence in `data/manifests/bdg2.json`.
- **Bandwidth:** downloads count against the BDG2 repository's Git LFS bandwidth. HTTP 403 or 429
  usually means rate limiting or an exhausted quota; try again later.

The first real download (2026-10-23) fetched all four files in 25 s. An independent `sha256sum`
matched every pinned hash, and a second `fetch` only verified (1.4 s).

### Data conventions

Quotes are from the paper (Europe PMC open-access copy, PMC7591488). The other findings were
checked on the downloaded files.

- **Shape:**
  - Electricity is **wide**: one `timestamp` column plus one column per building (1,578), over
    17,544 hourly rows from `2016-01-01 00:00:00` to `2017-12-31 23:00:00`.
  - Weather is **long**: `timestamp`, `site_id`, `airTemperature`, `cloudCoverage`,
    `dewTemperature`, `precipDepth1HR`, `precipDepth6HR`, `seaLvlPressure`, `windDirection`,
    `windSpeed`. There are 331,166 rows over 19 sites (16,860 to 17,544 hours per site).
  - Metadata has 1,636 rows and 32 columns, including `building_id`, `site_id`, `timezone`, `sqm`,
    `lat`, `lng` and `primaryspaceusage`.
- **Timestamps are local and carry no offset:** "Date and Time in the format YYYY-MM-DD hh:mm:ss
  in the local timezone", for weather and for meters. The paper adds that "the Building Data
  Genome 2 data set only has timestamps in the local time zone, including the weather data",
  unlike the Kaggle release.
- **A regular grid in daylight-saving zones (verified on the files):**
  - All 19 sites are in daylight-saving zones (`US/Eastern`, `US/Central`, `US/Mountain`,
    `US/Pacific`, `Europe/London`, `Europe/Dublin`).
  - Yet the electricity timestamps form a perfectly regular grid: no duplicates, every step
    exactly 1 h.
  - `2016-03-13 02:00:00`, which does not exist on US clocks, is present once.
  - `2016-11-06 01:00:00`, which occurs twice on US clocks, is present once.
- **The clock differs by site (T009a audit, D016).** T007's hypothesis, a single
  "local standard time" convention, **was tested and is wrong.** The audit tests each site's
  data using the daylight-saving transitions:
  - **Electricity is a human signal.** Schedules follow the wall clock. In standard-time
    timestamps the weekday profile therefore moves 1 h earlier after the spring change and back
    after the autumn change; in wall-clock timestamps it does not move. The audit compares the
    profiles 3 weeks before and after each of the 8 transitions in 2016–2017.
  - **A verdict needs strong agreement.** At least 2 usable transitions, at least 75% agreement,
    and the verdict must hold at every identifiability margin (0.0025, 0.005, 0.01).
  - **Conflicting signals are not resolved by guessing.** A "standard" verdict is overruled when
    the site's spring non-existent hour is systematically empty, which is the signature of
    wall-clock data forced onto a grid.
  - **Weather is a solar signal.** Every site has a real reading at each spring non-existent
    hour and no repeated timestamp, so its offset is fixed. No transition shows the wall-clock
    pattern, and the summer-minus-winter phase of the temperature cycle is −1.44 to +0.28 h,
    never the +1 h a wall clock would add. Weather is therefore taken as local standard time at
    every site.

  The resulting verdicts are pinned in
  [`bdg2_audit.py`](../backend/src/wattwise/data/bdg2_audit.py). They were obtained on the files
  at commit `753598e0a19400af950b1513e1daeb680658c1fd` and are reproducible with
  `uv run python -m wattwise.data.bdg2_audit`, which exits non-zero if the data stops matching
  them.

  | Site | Time zone | Buildings | Electricity clock | Weather clock |
  |---|---|---|---|---|
  | Bear | US/Pacific | 92 | wall_clock | standard |
  | Bobcat | US/Mountain | 35 | wall_clock | standard |
  | Bull | US/Central | 123 | wall_clock | standard |
  | Cockatoo | US/Eastern | 117 | wall_clock | standard |
  | Crow | US/Eastern | 5 | wall_clock | standard |
  | Eagle | US/Eastern | 106 | standard | standard |
  | Fox | America/Phoenix (published: US/Mountain) | 137 | standard | standard |
  | Gator | US/Eastern | 74 | wall_clock | standard |
  | Hog | US/Central | 152 | wall_clock | standard |
  | Lamb | Europe/London | 146 | wall_clock | standard |
  | Moose | US/Eastern | 13 | standard | standard |
  | Mouse | Europe/London | 7 | wall_clock | standard |
  | Panther | US/Eastern | 105 | wall_clock | standard |
  | Peacock | US/Eastern | 45 | wall_clock | standard |
  | Rat | US/Eastern | 305 | undetermined | standard |
  | Robin | Europe/London | 52 | undetermined | standard |
  | Shrew | Europe/London | 9 | undetermined | standard |
  | Swan | US/Pacific | 19 | undetermined | standard |
  | Wolf | Europe/Dublin | 36 | standard | standard |

  Reasons for the undetermined sites:
  - **Robin:** wall-clock at margins 0.0025 and 0.005, but not at 0.01.
  - **Rat:** the profile shifts indicate standard time, but its spring non-existent hours are
    systematically empty.
  - **Shrew and Swan:** too few or mixed transitions.

  **Fox** was undetermined under its published zone, `US/Mountain`: wall-clock at two margins
  only. Its metadata time zone was wrong. Since T009c it is audited in `America/Phoenix`, which
  has no clock changes, so its time is a fixed UTC−7 (see
  [Metadata corrections](#metadata-corrections-t009c)).

  **Consequences for conversion (T009b):**
  - **Standard sites:** add the fixed January offset. For `Europe/Dublin` that is 0, not the
    database's "standard" +1.
  - **Wall-clock sites:** localise in the zone. The spring non-existent hour and the single
    autumn repeated hour are **dropped and counted**, not guessed. At some sites that hour holds
    about twice a normal reading: two real hours summed.
  - **Undetermined sites** (4 of 19, 385 buildings, since T009c) are **excluded** with the
    reason recorded.
- **Shared weather stations:** some sites have identical weather (Mouse, Robin and Shrew; Crow
  and Moose; Panther and Gator).
- **Interval:** "Each row represents one hour, and the reading is the energy or water sum across
  that hour." The paper does not say whether the timestamp marks the start or the end of the
  hour. The data cannot settle this: a building opening at 08:00 with interval-start timestamps
  looks the same as one opening at 09:00 with interval-end timestamps. The canonical contract
  uses the start of the interval (D012), so T009b **explicitly assumes interval-start**. That is
  an at most 1-hour labelling uncertainty, which does not affect daily or weekly patterns.
- **Units:** "kWh sum for the energy-related meters and liters for the non-energy meters". Raw
  site units varied (kBTU, tons, lbs per hour, ...) and were converted by the BDG2 authors.
  Electricity therefore maps to canonical `kWh` unchanged. Water and irrigation would map from
  litres to `m3` by dividing by 1000, if ever used.
- **Raw vs cleaned:** in the cleaned files "outliers have been removed using the Twitter
  AnomalyDetection R library …, zero readings longer than 24 continuous hours are removed, and
  zero readings in electricity meters are removed". Cleaned data is better suited to training
  baselines. Raw data keeps the real anomalies, but they are unlabelled. Both are downloaded.
  The preprocessing pipeline uses cleaned data by default and raw data on request, and records
  the reason in its manifest (D017).
- **Weather alignment:** the 2020-06-24 correction suggests that a UTC/local mix-up was fixed.
  The T009a audit confirmed that weather is local standard time at every site (see above).

### Preparing BDG2 for analysis

From `backend/`, after `fetch`:

```bash
uv run python -m wattwise.data.bdg2_prepare                     # cleaned, 20 meters, seed 2016
uv run python -m wattwise.data.bdg2_prepare --variant raw       # raw readings instead
uv run python -m wattwise.data.bdg2_prepare --sample-meters 0   # every eligible meter
```

The pipeline (`wattwise.data.bdg2_prepare`, D017) does the following:
1. Verifies the inputs against the pinned checksums. `--skip-input-verification` skips this and
   records that it did.
2. Keeps electricity meters only.
3. Converts each site to UTC with its pinned clock, dropping and counting unconvertible hours.
4. Excludes meters without metadata, with an undetermined clock, or with readings in fewer than
   50% of hours (`--min-coverage`).
5. Draws a seeded random sample.

It writes the following to `data/processed/bdg2/<variant>/` (git-ignored, never committed):

| File | Content |
|---|---|
| `readings.parquet`, `buildings.parquet`, `weather.parquet` | Canonical tables ([DATA_CONTRACT.md](DATA_CONTRACT.md)); weather only for the sampled sites |
| `exclusions.csv` | Every meter not used, with one reason: `not_electricity`, `no_metadata`, `undetermined_clock`, `insufficient_data` or `not_sampled` |
| `quality_report.json`, `quality_report.md` | The T008 data-quality report ([DATA_QUALITY.md](DATA_QUALITY.md)) |
| `manifest.json` | Pinned commit, input and output SHA-256s, options, assumptions (variant, interval-start, clocks), statistics, licence note |

Identical inputs and options give byte-identical files.

**Current real run** (2026-10-24, pipeline version 2 with the T009c metadata corrections;
defaults: cleaned, 20 meters, seed 2016). These are observed counts for one seeded sample; they do
not describe all of BDG2.
- **Why the sample changed:** correcting Fox enlarged the eligible pool, so the seeded sample
  differs from the first run.
- **First run** (version 1): 1,013 eligible meters, 350,804 readings, 93.02% coverage.

| | |
|---|---|
| Electricity meters | 1,578. Excluded: 385 undetermined clock, 45 insufficient data. 1,148 eligible |
| Sample | 20 meters from 9 sites (Bull 2, Cockatoo 3, Eagle 3, Fox 1, Gator 2, Hog 4, Lamb 1, Panther 2, Peacock 2) |
| Readings | 350,816 rows, 2016-01-01T00:00Z to 2018-01-01T06:00Z. 7 sites are wall-clock (4 hours dropped per meter); Eagle and Fox are fixed-offset |
| Weather | 157,252 rows. Reading hours with weather: 96.75–99.99% per site |
| Quality | 95.65% coverage. Warnings for 16 of 20 meters: gaps 16 (including the 2-hour UTC gap at each autumn change), missing values 19, flatlines 12, low coverage 7 |
| Runtime | About 11 s on the development laptop. A second run gave byte-identical files |

The flatlines show that BDG2's cleaning removes zero runs but not constant non-zero runs.

### Licence

The sources disagree. Here is what each says, as verified on 2026-10-23:

| Source | Date | Licence stated | How verified |
|---|---|---|---|
| GitHub `LICENSE`, created and in force at the pinned commit | 2020-05-03 → 2023-10-13 | **MIT** (copyright the BUDS Group) | `LICENSE` at commits `d84391f` and `753598e` |
| Zenodo deposit of release v1.0, `10.5281/zenodo.3887306` | 2020-06-10 | **CC BY 4.0** | Zenodo API |
| Scientific Data article | 2020-10-27 | **CC BY 4.0** for the article; the article says CC0 applies to "the metadata files associated with this article" | Europe PMC full text |
| ORNL Open Energy Data Portal record (publisher: National University of Singapore) | record modified 2024-07-26 | **CC BY 4.0** | Portal API (Opendatasoft) |
| GitHub `LICENSE` on `master` | since 2023-10-14 (commit `9b97ccb`) | **CC BY-SA**: titled "Attribution-ShareAlike 4.0 Unported", but the text uses the 3.0 Unported legal-code wording ("Creative Commons Compatible License"); CC's 4.0 licences are named "International" | `LICENSE` at `9b97ccb` |

**How WattWise handles this.** This is an engineering record, not legal advice. WattWise
follows practices that satisfy the most restrictive reading, CC BY-SA:

1. **Attribution:** cite the paper, repository and Zenodo deposit, and link the licences wherever
   BDG2 data or results derived from it are shown.
2. **No redistribution:** raw and processed BDG2 data stay local (git-ignored) and are never
   committed or published from this repository. Only checksums and provenance are committed.
3. **Changes are documented:** every transformation of BDG2 data is described (T009) and
   reproducible from the pinned source.
4. **Public display is an open decision for the owner** (T038). If a public deployment shows
   BDG2 data or derived results, treat them as adaptations under CC BY-SA 4.0 (attribution and
   share-alike), or ask the maintainers to clarify the intended licence (e.g. a GitHub issue)
   before publishing.

## Supplementary data: evaluation (T007b)

BDG2 alone cannot support every part of the product. On 2026-10-24 this task searched for the
best available data for each gap, checking every candidate at its primary source. Each source
was checked for its publisher, access, licence, coverage and overlap with BDG2. Nothing has been
acquired yet; acquisition and integration are follow-up roadmap tasks. **Nothing here is
committed to the repository except this record.**

- **Double-checked:** a fact was confirmed a second time during this task, independently of the
  first research pass, by a repository API, a parse of the original file, or an official API.
- **Source-checked:** found at the primary source and not re-checked.
- **Unverified:** stated as such.

### Site geography (from BDG2 metadata)

The joins for carbon factors, prices, holidays and weather all depend on where each site is. The
location column comes from reverse-geocoding the metadata coordinates with OpenStreetMap
Nominatim (double-checked). Only the region is recorded here; nothing finer is needed.

Region codes are ISO 3166 codes (country, and subdivision where needed), pinned in
[`bdg2_sites.py`](../backend/src/wattwise/data/bdg2_sites.py). A test keeps this table in sync
with the code.

| Site | Metadata time zone | Location from coordinates | Note |
|---|---|---|---|
| Bear | US/Pacific | USA, California (US-CA) | |
| Bobcat | US/Mountain | no coordinates | |
| Bull | US/Central | USA, Texas (US-TX) | |
| Cockatoo | US/Eastern | USA, New York (US-NY) | |
| Crow | US/Eastern | **Canada, Ontario** (CA-ON) | The time rules match US/Eastern; the country does not |
| Eagle | US/Eastern | no coordinates | The country is unknown (see Crow) |
| Fox | US/Mountain, **corrected to America/Phoenix** | **USA, Arizona** (US-AZ) | Arizona does not observe daylight saving time (see below) |
| Gator | US/Eastern | no coordinates | The country is unknown |
| Hog | US/Central | USA, Minnesota (US-MN) | |
| Lamb | Europe/London | UK, Wales (GB-WLS) | |
| Moose | US/Eastern | **Canada, Ontario** (CA-ON) | |
| Mouse | Europe/London | UK, England (London) (GB-ENG) | |
| Panther | US/Eastern | USA, Florida (US-FL) | |
| Peacock | US/Eastern | USA, New Jersey (US-NJ) | |
| Rat | US/Eastern | USA, District of Columbia (US-DC) | |
| Robin | Europe/London | UK, England (London) (GB-ENG) | |
| Shrew | Europe/London | UK, England (London) (GB-ENG) | |
| Swan | US/Pacific | no coordinates | |
| Wolf | Europe/Dublin | **Ireland** (IE), after the longitude sign was corrected | As published, the coordinates fall in the Netherlands |

**Metadata problems found** (corrected with evidence in T009c; see
[Metadata corrections](#metadata-corrections-t009c)):
- **Wolf's longitude sign is flipped.** The metadata says `6.2603`; Dublin is at `−6.2603`.
- **Fox was in the wrong time zone.** Its coordinates are in Arizona, but its metadata said
  `US/Mountain`. This is now corrected.
- **The `US/...` prefix does not prove a site is in the US.** Crow and Moose are in Canada. The
  sites without coordinates (Bobcat, Eagle, Gator, Swan) therefore get **no** carbon factor,
  price or location-based weather.

### Metadata corrections (T009c)

The corrections are pinned in
[`bdg2_sites.py`](../backend/src/wattwise/data/bdg2_sites.py), each with its evidence (D020).
They are applied before the timestamp audit and before preparation, and recorded in every
manifest. A correction stops the pipeline if the published value differs from the data it was
made for.

| Site | Field | Published | Corrected | Evidence |
|---|---|---|---|---|
| Fox | time zone | `US/Mountain` | `America/Phoenix` | The coordinates are in Arizona, which does not observe daylight saving time. The readings pass the zone check (below) |
| Wolf | longitude | `6.2603` | `−6.2603` | As published, the coordinates fall in the Netherlands, while the time zone is Europe/Dublin; `53.3498, −6.2603` is Dublin |

**The zone check.** A corrected time zone without daylight saving time must agree with the
readings, examined under the *published* zone. Two things are checked, and failing either rejects
the correction and keeps the site excluded:
1. **No occupant shift:** no usable clock change may show occupants shifting their schedules, as
   standard-time data would.
2. **No fingerprint:** no clock-change hour may show the fingerprint of wall-clock data forced
   onto a regular grid. Each hour is compared with the same hour 1–3 weeks before and after:
   - an empty hour, or an empty neighbouring hour
   - copied or interpolated readings, at least 20 points above the control days
   - a jump of at least 0.25 in the hour's ratio to its neighbours (two hours merged)

**Result for Fox.** Accepted.
- **No occupant shift:** under US/Mountain, the lags at its four clock changes are 0, 0, +1 and
  0. None of these is the standard-time shift.
- **No fingerprint at any clock-change hour** (values from the audit output):
  - The spring hours are 0% and 0.7% empty, the same as their neighbours.
  - 2.9% and 2.2% of the spring readings look copied, against 4.4% and 3.5% on the control days.
  - The autumn hours have a ratio of 1.00 to their neighbours, against 1.00 on the control days.
- **Effect:** Fox's 137 buildings now convert at a fixed UTC−7. 135 of them are eligible; 2 have
  too little data.

**Falsification test.** The check was also run on the 18 other sites, as if each had been
"corrected" to a zone without daylight saving. It **rejected all 18**:
- all 11 wall-clock sites, for fingerprints (empty, displaced, filled or merged hours)
- all 3 standard-time sites, for occupant shifts
- the undetermined Rat, Robin, Shrew and Swan

Robin was rejected only after the rule was tightened from "no majority of shifts" to "no shift
at all": Robin shows one standard-time shift in four. Passing the check therefore does not prove a
zone. The coordinates are the evidence, and the check is a test the correction could fail.

### Recommendation by gap

| Gap | Recommended source | Licence | Status |
|---|---|---|---|
| Real anomaly labels | **LEAD 1.0**, public subset (200 buildings, 2016) | **None stated** (see below) | Owner decision on use |
| Carbon factors | US: **eGRID2016**. UK: **DESNZ conversion factors 2016/2017**. Ireland: **SEAI**. Ontario: **ECCC National Inventory Report** | Public domain / OGL v3.0 / reproduction with acknowledgement / OGL–Canada | Ready to integrate (T021a) |
| Electricity prices | US: **EIA-861** state commercial average. UK: **DESNZ Quarterly Energy Prices 3.4.1**. Ireland: **CSO TMEGB04**. Ontario: no adequate retail source, so kWh only | Public domain / OGL v3.0 / CC BY 4.0 | Ready to integrate (T021a) |
| Solar radiation | **ERA5** reanalysis, from the Copernicus CDS or Open-Meteo (`models=era5`). NASA POWER as a cross-check | CC BY 4.0; Open-Meteo's free tier is non-commercial only | Owner decision on access (T007d) |
| Humidity | **Derived** from BDG2 temperature and dew point; no new data | — | T007d |
| Holidays | **`holidays`** Python package | MIT | T013 |
| Daylight, sun position | **pvlib**, computed | BSD-3-Clause | T013 |
| Sub-metering, HVAC, occupancy | **LBNL Building 59**, then CU-BEMS, then HKUST | CC0 / CC BY 4.0 / CC0 | T040 |
| Independent buildings | **HKUST campus smart meters**. EnerNOC only if WattWise is non-commercial | CC0 / CC BY-NC 3.0 | T041 |
| Missing metadata (year built, occupants, …) | **No source.** BDG2 is anonymised, and nothing may be invented | — | Stays missing |
| Academic calendars | **No source found** for these anonymised campuses | — | Stays missing |

### Real anomaly labels: LEAD 1.0

- **What it is:** Gulati and Arjunan, *LEAD1.0: A Large-scale Annotated Dataset for Energy
  Anomaly Detection in Commercial Buildings*, ACM e-Energy 2022,
  [doi:10.1145/3538637.3539761](https://doi.org/10.1145/3538637.3539761) and
  [arXiv:2203.17256](https://arxiv.org/abs/2203.17256). The labels are human annotations of the
  GEPIII 2016 electricity data, which is BDG2's own meters.
- **Access:**
  - The repository [samy101/lead-dataset](https://github.com/samy101/lead-dataset) holds
    `data/lead1.0-small.zip`: **10,027,589 bytes** (double-checked).
  - It contains `lead1.0-small.csv` with the columns `building_id,timestamp,meter_reading,anomaly`,
    for 200 buildings (source-checked).
  - The full 1,413-meter release announced in the README never appeared. The two GitHub issues
    asking for it and for the test labels are open with no replies (double-checked).
  - The Kaggle competition copy (200 labelled and 206 unlabelled buildings) needs an account and
    acceptance of the competition rules.
- **Labels:**
  - A 0/1 flag per hourly reading, from about 100 person-hours of annotation with a visual tool.
  - Annotators marked unusual patterns and unusually high or low days. The paper reports no
    inter-annotator agreement and says "each building has a different definition of anomaly".
  - An annotated anomaly is **not** confirmed waste.
- **Joins to BDG2 (double-checked on a 117-hour sample):**
  - All 200 IDs map to BDG2 buildings through `building_id_kaggle`.
  - At zero time shift, **97.6%** of 21,804 readings equal BDG2 raw. At every shift from ±1 to ±6
    hours, at most 14% do.
  - So LEAD uses BDG2's local timestamps and each site's clock (D016).
  - Some readings differ: one Ontario site keeps GEPIII's original units, and mismatches cluster
    at labelled anomalies. **Use LEAD's labels with BDG2's readings**, not LEAD's readings.
- **Usable buildings:**
  - The 200 buildings are spread over 14 sites, mostly Bull 52, Eagle 47 and Lamb 24.
  - **173 are at sites with a determined clock**, including Fox's 21 since T009c. The other 27
    are at Robin and Rat.
  - Labels cover **2016 only**, so a chronological evaluation must stay within 2016.
- **Licence: unresolved.**
  - The GitHub repository has **no licence** (double-checked). An Apache-2.0 file was added and
    removed before the data was uploaded.
  - The Kaggle rules allow participants "any purpose, whether commercial or non-commercial" but
    forbid passing the data to non-participants.
  - The arXiv CC BY 4.0 licence covers the paper.
  - **Recommendation:** use it locally for evaluation only. Never commit or redistribute it, cite
    the paper, and ask the authors to clarify the licence.
  - **Owner decision (2026-10-24, D022):** accepted. LEAD is used locally for evaluation only.
- **Acquired and joined (T007c):**

  ```bash
  uv run python -m wattwise.data.lead fetch      # 10 MB into ../data/raw/lead
  uv run python -m wattwise.data.lead prepare    # labels into ../data/processed/lead
  ```

  - **Pinned download:** commit `80e13682`, 10,027,589 bytes, SHA-256 `b0e34c66…`. The download
    also matched GitHub's own git hash for the file (double-checked). Provenance is in
    [`data/manifests/lead.json`](../data/manifests/lead.json); the data is git-ignored.
  - **The join:** each label joins to its BDG2 meter by `building_id_kaggle` and local time,
    then converts to UTC with the site's audited clock. Only LEAD's labels are used, never its
    readings.
  - **Full-file result** (2026-10-24, byte-identical on a second run):

    | | |
    |---|---|
    | LEAD | 1,749,494 rows, 200 buildings, 37,296 anomalies |
    | Usable labels | **1,438,672 rows, 173 buildings, 31,166 anomalies (2.17%)** in 2016, across 12 sites |
    | Excluded rows | 236,714 at undetermined-clock sites (Robin and Rat); 73,925 not annotated (LEAD blanked the reading, so it was never judged); 183 daylight-saving hours with no single UTC time; 0 without a BDG2 match |
    | LEAD reading equals BDG2 raw | 98.41% of usable rows, but only **54.06% of usable anomalies (16,848 of 31,166)** |
    | Anomalies without a cleaned BDG2 reading | 22.85% |

  - **Rules for evaluation (T018):**
    1. **Score against BDG2's raw readings.** BDG2's cleaning removed 22.85% of the labelled
       anomalies.
    2. **Trust a label only where LEAD's reading equals BDG2's**
       (`lead_reading_matches_bdg2_raw`). At 14,318 labelled anomalies the readings differ:
       - Across all of LEAD's anomalies, 7,192 have a BDG2 reading of 0 where LEAD has a value.
       - Most of the others are far lower in LEAD (a median ratio of 0.05), often exactly 1.0
         where BDG2 has an ordinary value.
       - LEAD does not document why. Those labels describe data that differs from BDG2's, so they
         are reported separately.
    3. Moose's single building never matches (a units difference), so it is excluded by rule 2.
    4. The labels mark readings the annotators found unusual. They are not confirmed waste, and
       the annotators' agreement was never measured.
- **Alternatives considered** (fit for evaluating a whole-building hourly detector):
  - **LBNL fault detection datasets:** HVAC equipment, mostly simulated, 1-minute. Fit 1 of 5.
  - **REFIT annotated anomalies:** 5 houses, appliance level. Fit 1 of 5.
  - **Numenta Anomaly Benchmark:** no building electricity. Fit 1 of 5.
  - **ORNL fault simulations:** simulated, one building. Fit 2 of 5.
  - **Newer datasets:** no real-labelled whole-building electricity dataset newer than LEAD was
    found (2023–2026).

### Carbon factors

All of these are **annual average factors**. They are not marginal, and they are tied to the
year of the data.

| Geography | Source | 2016 | 2017 | Unit | Checked |
|---|---|---|---|---|---|
| USA, by eGRID subregion | [eGRID2016](https://www.epa.gov/egrid/historical-egrid-data) Table 1, total output CO2e. **There is no eGRID2017**; EPA advises using eGRID2016 for 2017 | AZNM 1,049.048 · CAMX 529.889 · NYUP 295.942 · RFCE 762.113 · U.S. 1,004.167 | as 2016 | lb CO2e/MWh | Double-checked (file parsed) |
| UK | DESNZ/BEIS [conversion factors](https://www.gov.uk/government/publications/greenhouse-gas-reporting-conversion-factors-2016), "electricity generated" | 0.41205 | 0.35156 | kg CO2e/kWh, plus T&D 0.03727 / 0.03287 | 2016 double-checked; 2017 source-checked |
| Ireland | SEAI, [Energy in Ireland 2018](https://www.seai.ie/publications/Energy-in-Ireland-2018.pdf) | 480 | 437 | g CO2/kWh, **CO2 only** | 2016 double-checked |
| Ontario | ECCC National Inventory Report 1990–2017, Table A13-7, consumption intensity | 40 | 20 (preliminary) | g CO2e/kWh, rounded | Double-checked |

- **Subregion mapping:** each US site will be mapped with a point-in-polygon lookup on the
  [eGRID2016 subregion shapefiles](https://www.epa.gov/energy/egrid-mapping-files). The current
  ZIP-code tool uses 2023 boundaries.
  - Expected subregions: CAMX (California), ERCT (Texas), NYUP (New York), AZNM (Arizona), MROW
    (Minnesota), FRCC (Florida), RFCE (New Jersey, DC). These are **unverified** until the
    lookup runs.
- **Non-baseload rates:** eGRID also gives them (e.g. CAMX 945.607 lb CO2e/MWh). EPA describes
  them as suited to avoided-emissions estimates.
- **Ruled out:**
  - The UK Carbon Intensity API (CC BY 4.0) starts in September 2017, too late.
  - WattTime and Electricity Maps coverage of 2016–2017 is unverified, and both are commercial
    services.

### Electricity prices

These are **averages, not a building's bill**. They leave out demand charges and time-of-use
pricing, and they are labelled as estimates wherever shown.

| Geography | Source | 2016 | 2017 | Unit | Checked |
|---|---|---|---|---|---|
| US states | EIA-861, "Total Electric Industry", commercial sector ([API](https://www.eia.gov/opendata/)) | AZ 10.41 · CA 15.07 · DC 11.72 · FL 8.90 · MN 9.86 · NJ 12.26 · NY 14.45 · TX 8.26 | AZ 10.50 · CA 15.76 · DC 11.66 · FL 9.35 · MN 10.48 · NJ 12.28 · NY 14.75 · TX 8.26 | US cents/kWh, nominal | AZ, NY, TX double-checked (EIA API); others source-checked |
| UK | DESNZ Quarterly Energy Prices, table 3.4.1, medium users, including Climate Change Levy | 10.01 | 10.49 | pence/kWh, excluding VAT | Source-checked |
| Ireland | CSO [TMEGB04](https://data.gov.ie/dataset/tmegb04-non-residential-electricity-prices), non-household, half-yearly | band ID 0.1018 / 0.1019 | band ID 0.1032 / 0.1006 | EUR/kWh, excluding VAT | Source-checked |
| Ontario | No verified retail commercial source. IESO wholesale components exclude delivery charges and are not openly licensed | — | — | — | Not adequate: kWh only |

The OpenEI Utility Rate Database (CC0, free API key) has historical tariffs, e.g. 2016 PG&E
commercial rates. But a building's actual tariff is unknown, so state averages are the honest
default.

### Weather enrichment

- **Humidity needs no new data.** It can be derived from BDG2's complete temperature and dew
  point, labelled "derived".
- **Solar radiation** is the important missing driver.
  - **ERA5 reanalysis** gives hourly global, direct and diffuse radiation for 2016–2017.
  - **[Copernicus CDS](https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels):**
    CC BY 4.0 since 2 July 2025, with no use restriction. It needs a free account and token.
  - **[Open-Meteo](https://open-meteo.com/en/docs/historical-weather-api):**
    - The same ERA5 data with no account. The data is CC BY 4.0, but the free API is for
      **non-commercial use only**, at under 10,000 calls a day (both double-checked).
    - Pin `models=era5`. The default blends a model that starts in 2017. ERA5-Land returned no
      radiation (source-checked).
  - **[NASA POWER](https://power.larc.nasa.gov/docs/services/api/temporal/hourly/):** has no use
    restrictions, but its radiation grid is coarse (1°), so it serves as a cross-check.
  - Reanalysis is **modelled, not observed**, and is labelled so. It covers only the 15 sites
    with coordinates.
- **Acquired (T007d, D023).** WattWise is non-commercial, so the Open-Meteo free API is used
  (owner decision, D022).

  ```bash
  uv run python -m wattwise.data.era5 fetch      # 15 requests, ~12 MB into ../data/raw/era5
  uv run python -m wattwise.data.era5 verify     # local copies against the manifest
  uv run python -m wattwise.data.era5 prepare    # ../data/processed/era5/weather_enrichment.parquet
  ```

  - **Request:** one per site with coordinates, pinned to `models=era5` and `timezone=GMT`,
    for 2015-12-31 to 2018-01-01 (a day of margin around BDG2's local years).
  - **Manifest:** [`data/manifests/era5.json`](../data/manifests/era5.json) records each
    request, the file's SHA-256, and a *content* hash. The content hash ignores the server's
    timing field, so a later re-fetch can prove the data has not changed. It also records the
    ERA5 grid cell and its distance from the site (2–14 km). The responses are git-ignored.
  - **Columns:** every column states its provenance by name.
    - `ghi_w_m2_era5`, `direct_horizontal_w_m2_era5`, `diffuse_horizontal_w_m2_era5`,
      `dni_w_m2_era5` and `cloud_cover_pct_era5` are modelled grid-cell values.
    - `relative_humidity_pct_derived` comes from BDG2's observed temperature and dew point.
    - Nothing is gap-filled across sources, and the 4 sites without coordinates have humidity
      only.
  - **Time convention, checked on the data.** Open-Meteo labels radiation with the end of the
    hour it averages, so radiation is relabelled to the start of its hour, as readings are.
    `prepare` fails unless two checks pass at every site:

    | Check | Result at all 15 sites (2026-10-24) |
    |---|---|
    | Radiation-weighted centre of each solar day vs solar noon (NOAA equation of time) | **−8.6 to +2.0 min** (548–731 days per site). Taking labels as interval starts would give +51 to +62 min |
    | ERA5 temperature vs BDG2 observed temperature | Best lag **0 h** at every site, r = 0.954–0.997. This also re-confirms the BDG2 weather clocks (D016) |

  - **Humidity:** the Magnus formula over water, with the Alduchov & Eskridge (1996)
    coefficients 17.625 and 243.04 °C. A dew point up to 0.5 °C above the air temperature is
    treated as rounding and capped at 100%; more than that is treated as an error and left
    missing. Neither case occurs in BDG2 (0 and 0).
  - **Result:** 334,020 rows, ERA5 for 15 sites and humidity for 19. The outputs were
    byte-identical on a second run, and a second `fetch` only verified the recorded files.
  - **Attribution, carried in every manifest and report:**
    - "Weather data by Open-Meteo.com", with a link (Zippenfenig 2023,
      [doi:10.5281/zenodo.7970649](https://doi.org/10.5281/zenodo.7970649)).
    - The ERA5 citation, Hersbach et al. 2023
      ([doi:10.24381/cds.adbb2d47](https://doi.org/10.24381/cds.adbb2d47)).
    - The Copernicus acknowledgement with its disclaimer.
    - The change made: radiation is relabelled.

    These texts were checked at Open-Meteo's licence page and the CDS dataset page.
  - **Request budget:** under the documented call weighting (a request counts as several calls
    beyond 10 variables or 14 days), the 15 requests count as about 785 calls, within the free
    limit of 10,000 a day.
  - **Validity:** the Magnus coefficients are the over-water form, valid from −40 to 50 °C.
- **Holidays:** `holidays` 0.107 (MIT, double-checked) covers the US states, Ontario,
  England/Wales and Ireland. Pin a release at least two weeks old. Public holidays are not
  campus closures, and **no source of academic calendars** for these anonymised campuses exists.
- **Daylight:** pvlib 0.16.1 (BSD-3-Clause, double-checked) computes sun position and clear-sky
  radiation from coordinates and UTC time.

### Sub-metered and independent buildings

| Dataset | What it adds | Licence | Size | Checked |
|---|---|---|---|---|
| [LBNL Building 59](https://doi.org/10.7941/D1N33Q) (Berkeley office, 2018–2020) | End uses (HVAC, lighting, plug loads), rooftop-unit and zone control points, **measured occupancy**, and dated real events (wildfire damper closures, COVID shelter-in-place) | CC0 | 263 MB zipped | Licence, size double-checked |
| [CU-BEMS](https://doi.org/10.6084/m9.figshare.11726517) (Bangkok office, 2018–2019, 1-minute) | Power for each air-conditioning unit, plus lighting and plug loads per zone | CC BY 4.0 | 16 files, 742 MB | Double-checked |
| [HKUST campus smart meters](https://doi.org/10.5061/dryad.k3j9kd5h6) (Hong Kong, 2022–2024) | More than 1,400 meters in more than 20 buildings, device-level sub-meters, an independent region and recent years | CC0 | 1.43 GB | Licence, size double-checked |
| EnerNOC GreenButton (100 US commercial sites, 2012, 5-minute) | Independent US multi-sector data | **CC BY-NC 3.0** | 67 MB | Source-checked |

- **Caveats:**
  - Building 59's gaps were imputed by its authors, so imputed spans must be masked.
  - CU-BEMS is a cooling-only tropical building.
  - HKUST's 15-minute meters are 23–52% missing.
- **Not independent of BDG2:**
  - Building Data Genome 1: 390 of its 507 buildings have a BDG2 building's exact floor area
    (an inference, not an ID match).
  - BuildingsBench includes BDG2.
  - NREL ComStock is simulated, and its licence statements conflict (CC BY 4.0, a BSD-style
    licence, "research purposes only"). It needs clarification before any use.
- **Data from another building cannot confirm a cause in a BDG2 building.** It can only test
  whether a detector reacts to a known kind of event. Causes in BDG2 remain hypotheses.

### Decisions for the owner

1. **LEAD licence:** use locally for evaluation only, never redistributed, with citation
   (recommended), or don't use it.
2. **Is WattWise non-commercial?** This decides whether the Open-Meteo free API and the EnerNOC
   data can be used. If not, use the Copernicus CDS (free account) and leave out EnerNOC.
3. **Carbon method** (decided in T021a):
   - Average or non-baseload US factors. Average factors are recommended, since they match the
     UK, Irish and Ontario sources.
   - Whether to apply the UK publisher's reporting-year convention (recommended).

## Synthetic sample

Generated by `wattwise.data.synthetic` and fully documented in its
[README](../data/sample/synthetic/README.md). It contains no real measurements, and results on it
are reported as synthetic benchmarks only (D013).
