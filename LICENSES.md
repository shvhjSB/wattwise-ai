# Licences

What WattWise AI's own code is released under, the terms of every dataset it uses, and the
licences of the third-party software it ships. This file states what each source declares; it is
not legal advice. Where a source is ambiguous, WattWise follows the most restrictive reading.

## WattWise code

The code in this repository is released under the [MIT License](LICENSE). That covers the
backend, frontend, scripts, tests, documentation and the generated synthetic sample in
`data/sample/synthetic/`, which contains no real measurements.

## Data

**No raw or processed third-party dataset is committed or redistributed.** `data/raw/` and
`data/processed/` are git-ignored, and datasets are obtained by an explicit, checksum-verified
command. Provenance and download instructions: [docs/DATASETS.md](docs/DATASETS.md).

| Data | Used for | Licence as declared | How WattWise uses it |
|---|---|---|---|
| [Building Data Genome Project 2](https://github.com/buds-lab/building-data-genome-project-2) (Miller et al. 2020, [doi:10.1038/s41597-020-00712-x](https://doi.org/10.1038/s41597-020-00712-x)) | Readings, building metadata and weather for training and evaluation | **Inconsistent between sources:** MIT (repository at the pinned commit), CC BY 4.0 (Zenodo, article, ORNL portal), CC BY-SA (repository since 2023-10-14) | Follows the most restrictive reading, **CC BY-SA**: attributes the source and never redistributes raw or derived data (D014). Site coordinates are not committed. |
| [LEAD 1.0](https://github.com/samy101/lead-dataset) anomaly labels | Checking the detectors against human labels (T018b, T044c) | **None stated** in the repository; the Kaggle rules forbid passing the data to non-participants | **Local evaluation only, never committed or redistributed**, with citation (owner decision, D022) |
| ERA5 reanalysis (Hersbach et al. 2023, [doi:10.24381/cds.adbb2d47](https://doi.org/10.24381/cds.adbb2d47)) via [Open-Meteo](https://open-meteo.com) (Zippenfenig 2023, [doi:10.5281/zenodo.7970649](https://doi.org/10.5281/zenodo.7970649)) | Solar radiation and cloud cover features | **CC BY 4.0**; Open-Meteo's free API is for **non-commercial** use | Used because the owner declared the project non-commercial (D022, D023). Attribution and the Copernicus acknowledgement are carried in every manifest and report. A commercial use would switch to the Copernicus CDS. |
| [`data/reference/carbon_factors.csv`](data/reference/carbon_factors.csv) | Sourced carbon factors (T021a) | Per row: EPA eGRID2016, **US Government Work (public domain)**; DESNZ 2016/2017 conversion factors, **Open Government Licence v3.0**; SEAI *Energy in Ireland 2018*, **reproduction with acknowledgement** | Committed as small, cited reference tables; every row carries its source, URL, retrieval date, licence and file SHA-256 |
| [`data/reference/electricity_prices.csv`](data/reference/electricity_prices.csv) | Published price references (T021a) | Per row: EIA, **US Government Work (public domain)**; DESNZ Quarterly Energy Prices, **Open Government Licence v3.0**; CSO TMEGB04, **CC BY 4.0** | As above. A price is never applied by default; a user chooses it as a scenario (D054). |
| `holidays` package data | Public-holiday features | MIT (package licence) | Installed dependency, see below |

**Not yet used:** LBNL Building 59 (CC0) and the HKUST campus smart-meter database (CC0) are
planned for T040 and T041. They are not downloaded or committed.

## Third-party software shipped in the containers

The API image installs exactly the locked runtime dependencies (no development tools); the
frontend image serves a static bundle that includes React. Licences below are **as declared in
each package's own metadata**, read from the installed packages on 2026-11-01 (the Linux-only
`uvloop` from inside the API image). Versions are the locked ones in `backend/uv.lock` and
`frontend/package-lock.json`.

### Python runtime dependencies (API image)

| Package | Version | Declared licence |
|---|---|---|
| alembic | 1.20.0 | MIT |
| annotated-doc | 0.0.5 | MIT |
| annotated-types | 0.8.0 | MIT |
| anyio | 4.15.1 | MIT |
| click | 8.5.0 | BSD-3-Clause |
| cloudpickle | 3.1.2 | BSD |
| fastapi | 0.161.1 | MIT |
| greenlet | 3.5.6 | MIT AND PSF-2.0 |
| h11 | 0.16.0 | MIT |
| holidays | 0.106 | MIT |
| httptools | 0.9.0 | MIT |
| idna | 3.20 | BSD-3-Clause |
| joblib | 1.6.0 | BSD-3-Clause |
| lightgbm | 4.7.0 | MIT |
| Mako | 1.4.3 | MIT |
| MarkupSafe | 3.0.4 | BSD-3-Clause |
| narwhals | 2.27.1 | MIT |
| numpy | 2.5.4 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 |
| opentelemetry-api | 1.45.1 | Apache-2.0 |
| pandas | 3.0.6 | BSD |
| **psycopg** | 3.3.6 | **LGPL-3.0-only** |
| **psycopg-binary** | 3.3.6 | **LGPL-3.0-only** |
| pyarrow | 26.0.0 | Apache-2.0 |
| pydantic | 2.14.1 | MIT |
| pydantic_core | 2.50.1 | MIT |
| pydantic-settings | 2.16.1 | MIT |
| python-dateutil | 2.9.0.post0 | Apache-2.0 or BSD (dual) |
| python-dotenv | 1.2.4 | BSD-3-Clause |
| python-multipart | 0.0.32 | Apache-2.0 |
| PyYAML | 6.0.3 | MIT |
| scikit-learn | 1.9.1 | BSD-3-Clause |
| scipy | 1.18.1 | BSD |
| six | 1.17.0 | MIT |
| SQLAlchemy | 2.0.54 | MIT |
| starlette | 1.9.0 | BSD-3-Clause |
| threadpoolctl | 3.7.0 | BSD-3-Clause |
| typing_extensions | 4.16.0 | PSF-2.0 |
| typing-inspection | 0.4.4 | MIT |
| tzdata | 2026.5 | Apache-2.0 |
| uvicorn | 0.54.0 | BSD-3-Clause |
| uvloop (Linux only) | 0.23.0 | MIT or Apache-2.0 |
| watchfiles | 1.3.0 | MIT |
| websockets | 17.3 | BSD-3-Clause |

**psycopg is LGPL-3.0.** WattWise uses it unmodified, as a separately installed library, and
does not combine it into its own code. Anyone redistributing the API image should keep psycopg's
licence text and source availability (its source is published on PyPI and GitHub).

### Frontend runtime dependencies (in the built bundle)

| Package | Version | Declared licence |
|---|---|---|
| react | 19.3.1 | MIT |
| react-dom | 19.3.1 | MIT |
| scheduler | 0.28.0 | MIT |

### Container base images

Both images and the database are built from official, digest-pinned images: `python:3.13-slim-bookworm`
(API), `node:24-bookworm` (frontend build stage only, not shipped) and `nginx:stable-alpine`
(frontend runtime), and `postgres:18`. Each carries the licences of its own distribution's
packages (Debian, Alpine, PostgreSQL License, BSD-2-Clause for nginx).

### Development tools

Test, lint, type-check and build tools (pytest, ruff, mypy, Vitest, ESLint, Prettier, TypeScript,
Vite, Tailwind CSS, Playwright and others) are used to develop and check WattWise but are **not
shipped** in either runtime image. Their licences are in their own package metadata.

## Keeping this file current

Regenerate the dependency tables when `backend/uv.lock` or `frontend/package-lock.json` changes:
read each runtime package's declared licence from its installed metadata, not from memory.
