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
- **But not daylight-saving wall-clock time (verified on the files):**
  - All 19 sites are in daylight-saving zones (`US/Eastern`, `US/Central`, `US/Mountain`,
    `US/Pacific`, `Europe/London`, `Europe/Dublin`).
  - Yet the electricity timestamps form a perfectly regular grid: no duplicates, every step
    exactly 1 h.
  - `2016-03-13 02:00:00`, which does not exist on US clocks, is present once.
  - `2016-11-06 01:00:00`, which occurs twice on US clocks, is present once.
  - Converting with a daylight-saving-aware zone would fail on those hours, or shift data by an
    hour for half the year. The likeliest explanation is local *standard* time (a fixed offset),
    but this is a **hypothesis for T009 to test** against the data, e.g. load-profile shifts
    around the changeover dates.
- **Interval:** "Each row represents one hour, and the reading is the energy or water sum across
  that hour." The paper does not say whether the timestamp marks the start or the end of the
  hour. The canonical contract uses the start of the interval (D012), so **T009 must determine or
  explicitly assume** the convention.
- **Units:** "kWh sum for the energy-related meters and liters for the non-energy meters". Raw
  site units varied (kBTU, tons, lbs per hour, ...) and were converted by the BDG2 authors.
  Electricity therefore maps to canonical `kWh` unchanged. Water and irrigation would map from
  litres to `m3` by dividing by 1000, if ever used.
- **Raw vs cleaned:** in the cleaned files "outliers have been removed using the Twitter
  AnomalyDetection R library …, zero readings longer than 24 continuous hours are removed, and
  zero readings in electricity meters are removed". Cleaned data is better suited to training
  baselines. Raw data keeps the real anomalies, but they are unlabelled. Both are downloaded;
  T009 and T012 decide which to use for what, and record why.
- **Weather alignment:** the 2020-06-24 correction suggests that a UTC/local mix-up was fixed.
  T009 should confirm that weather is local, e.g. that temperature peaks in the local afternoon.

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
