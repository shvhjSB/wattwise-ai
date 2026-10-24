# WattWise AI

**Explainable energy-waste intelligence for commercial buildings.**

> **Status: early development.** The repository foundation, the backend API skeleton and the
> frontend shell are in place, but no model has been trained and no metrics exist yet. Nothing in this repository should be read as a measured
> result until it appears in the evaluation documentation with the command that produced it.
> See [docs/PROJECT_STATUS.md](docs/PROJECT_STATUS.md) for the live status.

## The problem

Commercial buildings waste a meaningful share of their energy through HVAC running after hours,
equipment left on, drifting control schedules, and faulty meters. Operators rarely lack data.
What they lack is a defensible answer to *"is this consumption normal, and is it worth my time?"*

WattWise AI is being built to help a building operator answer five questions:

1. What should this building's consumption normally be under comparable conditions?
2. When and where is consumption behaving abnormally?
3. How much excess energy might have been consumed?
4. What evidence supports the alert, and how uncertain is the estimate?
5. Which anomaly should be investigated first, based on potential business impact?

## Approach

The core idea is an **explainable counterfactual energy baseline**: a model of what a meter
*would* have consumed under the observed weather, calendar and building conditions if behaviour
had stayed normal. Comparing observed with expected consumption, together with an uncertainty
interval, lets the system:

- flag anomalies (spikes, sustained excess, overnight base load, drift, flatlined meters, data faults);
- estimate **potential** excess kWh, counted only above a conservative upper bound;
- translate that into an **estimated** cost when a tariff is explicitly configured;
- rank alerts by likely impact, persistence and confidence;
- capture operator feedback for later evaluation.

An anomaly is not confirmed waste, and feature attributions are not causes. The product is
designed to say so wherever it shows a result.

## Planned architecture

| Layer | Technology |
|---|---|
| Frontend | React, TypeScript, Vite, Tailwind CSS, interactive charts |
| API | Python, FastAPI, Pydantic, SQLAlchemy, Alembic, PostgreSQL |
| ML | pandas, NumPy, scikit-learn, LightGBM (only if it beats simple baselines), SHAP |
| Operations | Docker Compose, GitHub Actions, environment-based configuration |

```
backend/     Python project "wattwise": API now; data pipeline and ML code to follow (src layout)
frontend/    React + TypeScript + Vite application
scripts/     dataset acquisition, preprocessing, training and evaluation entry points (planned)
data/        sample/ = tiny synthetic fixtures (committed); raw/ and processed/ are git-ignored
docs/        roadmap, decisions, status, work log, specifications
```

## Data

The primary dataset is the [Building Data Genome Project 2](https://github.com/buds-lab/building-data-genome-project-2)
(Miller et al., 2020, *Scientific Data* 7, 368, <https://doi.org/10.1038/s41597-020-00712-x>).
Raw data is never committed. Downloading it is an explicit, checksum-verified command
(`uv run python -m wattwise.data.bdg2 fetch`, about 369 MB). A second command,
`uv run python -m wattwise.data.bdg2_prepare`, converts it to canonical tables in git-ignored
`data/processed/`. It uses each site's audited timestamp clock and logs every excluded meter
with a reason. Provenance, licence evidence and the data conventions are in
[docs/DATASETS.md](docs/DATASETS.md). All data,
whether from a dataset or an upload, is converted to one canonical shape, described in
[docs/DATA_CONTRACT.md](docs/DATA_CONTRACT.md), including the CSV upload format. Data quality (gaps, flatlines,
unit slips and more) is assessed and reported, never silently fixed:
[docs/DATA_QUALITY.md](docs/DATA_QUALITY.md). Tests and the
demo mode use a small, deterministic and clearly **synthetic** dataset with labelled injected
anomalies: [data/sample/synthetic/](data/sample/synthetic/README.md).

BDG2's licence is stated differently by its sources (MIT, CC BY 4.0, CC BY-SA). WattWise follows
the most restrictive reading: it attributes the source and never redistributes raw or derived
BDG2 data (see [docs/DATASETS.md](docs/DATASETS.md#licence)). Other candidate datasets are listed
in [docs/specs/DATASET_CATALOG.md](docs/specs/DATASET_CATALOG.md).

## Quickstart

The application foundation runs locally today:

1. **Backend:** start the API, which serves a liveness endpoint and OpenAPI docs. See
   [backend/README.md](backend/README.md).
2. **Frontend:** run `npm ci` and `npm run dev` in `frontend/`, then open
   <http://127.0.0.1:5173>. It shows the live API connection status. See
   [frontend/README.md](frontend/README.md).

No energy data, models or analytics exist yet. The one-command Docker Compose quickstart
arrives with task T036.

## Project records

- [docs/ROADMAP.md](docs/ROADMAP.md): milestones, tasks and acceptance criteria
- [docs/PROJECT_STATUS.md](docs/PROJECT_STATUS.md): current status and next task
- [docs/DECISIONS.md](docs/DECISIONS.md): architecture and ML decisions with alternatives
- [docs/WORK_LOG.md](docs/WORK_LOG.md): chronological checkpoint log
- [CHANGELOG.md](CHANGELOG.md): notable changes
- [docs/specs/](docs/specs/): the original product and dataset specifications

## Licence

Code is released under the [MIT License](LICENSE). Datasets keep their own licences. They are
not redistributed here.
