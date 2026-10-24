# WattWise AI — Datasets

Which datasets WattWise uses, where they come from, how to obtain them, their licences, and the
conventions an adapter must respect. **No external dataset is committed to this repository.**
Raw downloads live under `data/raw/` and processed tables under `data/processed/`; both are
git-ignored. Only the small synthetic sample and provenance manifests are committed.

| Dataset | Role | In the repository? | How to obtain |
|---|---|---|---|
| Synthetic sample | Tests, demo mode, synthetic benchmarks | Yes: [`data/sample/synthetic/`](../data/sample/synthetic/README.md), about 564 KB | Generated: `uv run python -m wattwise.data.synthetic` |
| Building Data Genome Project 2 (BDG2) | Primary real data for forecasting and anomaly detection | **No.** Only the manifest [`data/manifests/bdg2.json`](../data/manifests/bdg2.json) | Explicit download, about 369 MB (below) |
| Other candidates (ASHRAE GEPIII, REFIT, UCI, eGRID, URDB, Open-Meteo) | Not used yet | No | See [specs/DATASET_CATALOG.md](specs/DATASET_CATALOG.md) |

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
  | Fox | US/Mountain | 137 | undetermined | standard |
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
  - **Fox and Robin:** wall-clock at margins 0.0025 and 0.005, but not at 0.01.
  - **Rat:** the profile shifts indicate standard time, but its spring non-existent hours are
    systematically empty.
  - **Shrew and Swan:** too few or mixed transitions.

  **Consequences for conversion (T009b):**
  - **Standard sites:** add the fixed January offset. For `Europe/Dublin` that is 0, not the
    database's "standard" +1.
  - **Wall-clock sites:** localise in the zone. The spring non-existent hour and the single
    autumn repeated hour are **dropped and counted**, not guessed. At some sites that hour holds
    about twice a normal reading: two real hours summed.
  - **Undetermined sites** (5 of 19, 522 buildings) are **excluded** with the reason recorded.
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

**First real run** (2026-10-24, defaults: cleaned, 20 meters, seed 2016). These are observed
counts for one seeded sample; they do not describe all of BDG2.

| | |
|---|---|
| Electricity meters | 1,578. Excluded: 522 undetermined clock, 43 insufficient data. 1,013 eligible |
| Sample | 20 meters from 9 sites (Bull 3, Cockatoo 3, Crow 1, Eagle 1, Gator 1, Hog 4, Lamb 3, Panther 2, Peacock 2) |
| Readings | 350,804 rows, 2016-01-01T00:00Z to 2018-01-01T05:00Z. 8 sites are wall-clock (4 hours dropped per meter), Eagle is standard |
| Weather | 156,569 rows. Reading hours with weather: 96.1–99.98% per site |
| Quality | 93.02% coverage. Warnings for 18 of 20 meters: gaps 19 (including the 2-hour UTC gap at each autumn change), missing values 18, flatlines 12, low coverage 10 |
| Runtime | About 12 s on the development laptop. A second run gave byte-identical files |

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

## Synthetic sample

Generated by `wattwise.data.synthetic` and fully documented in its
[README](../data/sample/synthetic/README.md). It contains no real measurements, and results on it
are reported as synthetic benchmarks only (D013).
