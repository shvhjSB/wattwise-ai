# Claude Code Master Build Prompt — WattWise AI

Paste this whole prompt into Claude Code from the root of your existing `wattwise-ai` Git repository. Let Claude inspect the repository before changing files.

---

You are the senior ML engineer, data engineer, backend engineer, frontend engineer, product designer, QA engineer, and deployment engineer for **WattWise AI**. Build this as a credible, recruiter-ready, end-to-end machine-learning product—not a toy dashboard and not a Streamlit app.

## Product vision

WattWise AI is an explainable energy-waste intelligence platform for offices, hotels, campuses, retail buildings, and factories. It learns a building/meter's expected energy use under comparable operating conditions, spots unusual patterns, estimates *potential* excess consumption and cost, explains the evidence, and helps a human operator triage the alert.

The differentiator is the combination of:
1. A weather/calendar/building-aware **counterfactual consumption baseline** (what consumption was expected to be if behaviour had remained normal).
2. A robust anomaly detection layer that detects several *patterns*, not just generic spikes: sustained excess baseload/overnight usage, sudden spikes, gradual drift, flatlined/stuck meters, and missing/stale data.
3. **Uncertainty-aware waste estimates**: calculate excess kWh only when actual consumption is above a conservative upper prediction threshold, and show the assumptions and interval. Never claim estimated excess energy is confirmed savings.
4. Evidence-backed explanations with contributing signals and links to the relevant chart/time window. Use SHAP where technically appropriate, plus transparent rules. Do not invent physical causes; phrase causes as investigation hypotheses.
5. A prioritisation queue ranking alerts by estimated financial impact, persistence, severity, and confidence—not by anomaly score alone.
6. A human feedback workflow: operators can mark an alert as confirmed waste, expected behaviour, sensor/data fault, or needs investigation. Persist feedback and show the feedback count; do not pretend the feedback has retrained a model until an actual retraining workflow exists.
7. A visible model-evaluation lab that shows baselines, time-based evaluation, false-alert rates, and data drift. Results must be generated from real runs, not fabricated.

Do not claim WattWise is the first or best product in the industry. Build a technically rigorous and distinctive portfolio demonstration.

## First actions (mandatory)

1. Inspect the current repository, `README`, dependency files, and existing tests. Do not blindly replace working code.
2. Write `IMPLEMENTATION_PLAN.md` with the repo assessment, milestones, key risks, and verification commands. Then implement the plan in small, testable stages.
3. If data are not available, the app must still run using clearly labelled deterministic synthetic demo data. Do not label simulated results as real.
4. Never commit raw datasets, API keys, secrets, `.env` files, local DBs, large model artifacts, or personal data. Add robust `.gitignore` rules.
5. After each milestone run relevant tests/builds. Fix failures before moving on. Never say a command passed unless you ran it and observed the result. At the end report exactly what was tested, what was not tested, and any manual step still required.

## Required technology stack

- Frontend: React + TypeScript + Vite, modern component architecture, accessible responsive UI, professional visual hierarchy, charts using Recharts or ECharts, a polished dark/light theme.
- Backend: Python FastAPI, Pydantic schemas, SQLAlchemy, Alembic migrations, PostgreSQL in deployed/local Docker setup, pytest, structured logging, OpenAPI docs.
- ML/data: pandas, NumPy, scikit-learn, LightGBM (if installable in the target environment; otherwise a documented fallback), joblib, SHAP as an optional explanation dependency. Keep ML code separate from API route code.
- Operations: Dockerfiles, Docker Compose, health checks, environment variables, Nginx only if needed, CI with frontend lint/typecheck/build + backend tests, deployment configuration and documentation.
- No Streamlit. No fabricated external API integration. Core demo must work with no paid API key.

## Architecture expectations

Use a clear monorepo layout such as:
- `frontend/` React application
- `backend/` FastAPI application, models, schemas, services, repositories
- `ml/` or `backend/app/ml/` reusable feature engineering, training, inference, evaluation, and model registry/artifact-loading code
- `data/sample/` tiny committed fixture data only
- `data/raw/` and `data/processed/` ignored by git
- `scripts/` dataset setup, validation, preprocessing, training, and evaluation entry points
- `tests/` unit, integration, data-contract, and API tests
- `docs/` architecture, dataset cards, model card, evaluation protocol, decisions, and deployment guide
- root `docker-compose.yml`, `.env.example`, CI workflow, `README.md`, `LICENSES.md`

Adapt names to the existing repo if it already has a clean equivalent; don't duplicate structure unnecessarily.

## ML requirements

### A. Dataset and data validation
- Build a configurable loader for the Building Data Genome Project 2 (BDG2) dataset. It contains separate meter time-series, metadata, and weather data; inspect its actual columns/files rather than assuming one fixed schema.
- Support electricity meters first. Keep non-electric meter types labelled and either supported intentionally or excluded with an explicit reason. Never combine different energy units without conversion and documentation.
- Normalize timestamps/time zones carefully, preserve meter/building IDs, detect duplicate timestamps, missing values, outliers, flatlines, gaps, and implausible units.
- Produce a data-quality report before training: row counts, date ranges, meter counts, missingness, duplicate rate, gaps, unit assumptions, excluded rows, and selected buildings/meters.
- Provide a documented smaller-data mode for laptop development. Training must be reproducible with a fixed random seed.
- Include dataset provenance, attribution, licence text/URL and retrieval date in `docs/DATASETS.md`/`LICENSES.md`. Dataset license metadata can differ by mirror; record the source actually used and flag unresolved ambiguity. Do not redistribute raw data in the Git repository.

### B. Forecasting / counterfactual baseline
- Predict expected meter consumption using calendar features, lags/rolling statistics, meter identity and available building metadata, and weather features where available.
- Compare at least: a seasonal naive baseline, a statistical/linear baseline, and a tree-based model (e.g. LightGBM or HistGradientBoostingRegressor). A complex model must beat or justify itself against the simple baseline.
- Split by time (no random row split for time series); provide rolling-origin or expanding-window validation. Prevent target leakage in lags, rolling features, transformations, imputation, and feature selection.
- Report MAE and RMSE, plus WAPE only where its denominator is valid. Report per-meter/building metrics and macro averages; document limitations.
- Produce prediction intervals or an explicitly conservative uncertainty estimate. Do not call model intervals calibrated unless calibration is tested.

### C. Anomaly detection and classification
- Implement robust residual-based detection: observed minus predicted, normalized by prediction uncertainty or a robust residual scale. Add a complementary unsupervised detector (e.g. Isolation Forest) only if it adds measured value.
- Add transparent signature rules for spike, sustained elevated usage, overnight/base-load anomaly, gradual drift, flatline/stuck meter, and data-quality fault. Make thresholds configurable and explain each one.
- Use persistence/hysteresis or grouping so one long event does not create dozens of duplicate alerts. Track event start/end, magnitude, severity, confidence, and status.
- Be explicit that unsupervised anomalies are not ground-truth faults. Evaluate with labelled data where available and carefully designed synthetic perturbation tests; clearly separate synthetic benchmark results from real-world performance.
- Evaluate precision/recall/F1 only when labels are valid; otherwise report alert volume, stability, detection latency on injected events, and false-positive review results separately.

### D. Explainability and estimated impact
- For every alert return actual, expected baseline, residual, threshold/interval, persistence, relevant time range, important input signals, and an understandable explanation.
- SHAP is supplemental and must be computed safely; do not block inference if it is unavailable. Never state a causal explanation from feature importance alone.
- Calculate `potential_excess_kwh` transparently using a documented lower/upper baseline rule; do not make negative excess look like waste. Use a configurable tariff in currency per kWh and an explicit currency code. If tariff is unknown, show kWh only and ask for configuration—never invent a local tariff.
- Calculate carbon impact only from a sourced/configured regional emissions factor with source/year metadata. If the factor is absent, show “not configured,” not a guessed number.
- Label money/carbon values as estimates; include assumptions, currency, factor source, time coverage, and uncertainty wherever shown.
- Recommendations should be a deterministic, auditable rule-based triage helper mapped from observable signatures (e.g., verify schedule, inspect sensor, compare similar days). Do not claim the system knows which equipment caused a pattern.

### E. Human feedback and model operations
- Persist alert review labels and reviewer notes with created/updated timestamps; validate inputs and protect against injection.
- Create model metadata/version records including training period, dataset fingerprint, code/config version, feature list, metrics, created_at, and model artifact path.
- Include a training CLI and evaluation CLI. Model replacement must be atomic and handle a missing model gracefully. Explain a safe retraining workflow; do not automatically retrain on feedback without enough vetted labels.

## API endpoints (at minimum)

- `GET /api/v1/health` and `GET /api/v1/ready`
- `GET /api/v1/dashboard/summary?start=...&end=...&building_id=...`
- `GET /api/v1/buildings`, `GET /api/v1/meters`
- `GET /api/v1/meters/{meter_id}/series?start=...&end=...`
- `GET /api/v1/alerts` with pagination and filters, `GET /api/v1/alerts/{alert_id}`
- `POST /api/v1/alerts/{alert_id}/feedback`
- `POST /api/v1/data/upload` for CSV with a strict size limit, schema validation, safe filenames, no arbitrary file path access, and a useful error report
- `POST /api/v1/inference/analyze` for one validated series or uploaded dataset
- `GET /api/v1/models/metrics`, `GET /api/v1/models/metadata`
- Optional admin-protected endpoint to trigger training; never expose arbitrary shell execution through the API.

Version endpoints, define Pydantic request/response schemas, sensible HTTP status codes, pagination, filtering, CORS allow-list from environment, request size/time limits, safe exception handlers, and health checks. Keep Swagger/OpenAPI useful.

## Frontend experience

Design it like a mature enterprise energy intelligence product, not a generic admin template:
- Premium, clean layout with restrained accent colors, excellent spacing/typography, responsive design and accessible contrast.
- Overview: total measured kWh, model-expected kWh, estimated excess kWh (clearly marked estimate), active anomaly events, data-quality health, and data coverage. Every KPI should have a source/definition tooltip.
- Portfolio heatmap/list to compare buildings and meters; don't imply geographic coordinates exist if they do not.
- Anomaly inbox ordered by likely business impact, with filters for building, meter, signature, severity, confidence, review status and date.
- Alert detail: synchronized actual-versus-expected time-series plot, prediction interval, residual view, event timeline, explanation/evidence, assumptions, suggested checks, and operator feedback buttons.
- Energy “counterfactual lab”: compare actual data against baseline and let users explore scenario parameters without rewriting historical truth.
- Model lab: evaluation windows, baseline comparison, metrics, per-building breakdown, training metadata and clear warnings when metrics are unavailable.
- Dataset health page: ingestion summary, missing data, duplicate timestamps, flatlines, out-of-range values and recent uploads.
- Demo-data banner / provenance badge whenever synthetic data is being shown. Handle loading, empty, offline and error states; no fake live counts, fake savings or placeholder charts presented as real.
- Use reusable typed API client, environment-based API URL, and frontend tests for key flows.

## Deployment / security

- `docker compose up --build` should start the whole stack locally and document the ports. Include PostgreSQL health checks, service dependencies, persistent named volume and startup/migration instructions.
- Configure production via environment variables; provide `.env.example` but no real secrets.
- Configure CORS to the deployed UI URL; don't use `*` in production.
- Add CI to install, lint/typecheck, test, and build. Pin or constrain dependencies, document upgrade steps, and add vulnerability hygiene where practical.
- Provide a Render Blueprint or equivalent low-cost deploy recipe for frontend + FastAPI API + managed PostgreSQL. Don't assume local container file storage persists in the cloud. Store uploaded files/model artifacts on persistent storage or clearly state demo-only storage limitations.
- Include deployment readiness checks, logs, migrations, rollback/model version notes, and troubleshooting. Do not claim the app is publicly deployed unless it actually is.

## Documentation deliverables

- Strong README: what business problem it solves, architecture diagram (Mermaid), screenshots instructions, features, quickstart, API docs, ML methodology, metrics definitions, limitations, sample demo workflow, deployment, roadmap.
- `docs/DATASETS.md`: URLs, what each dataset contributes, file locations/expected columns, licence/citation/attribution, download instructions, and which modes work without data downloads.
- `docs/MODEL_CARD.md`: training data, intended use, prohibited/unsupported conclusions, metrics, evaluation split, data leakage protections, known biases, and failure modes.
- `docs/ARCHITECTURE.md`, `docs/DEPLOYMENT.md`, `docs/DECISIONS.md`.
- Keep sample data small and explicitly synthetic; never commit the full external datasets.

## Acceptance criteria

1. Fresh clone can run with Docker Compose using synthetic demo data and no paid keys.
2. React production build succeeds; FastAPI tests pass; API integration tests work.
3. Training/evaluation commands work against a documented downloaded dataset or fail with a helpful, actionable message if data are absent.
4. No random row split for time series; no target leakage; temporal test window is strictly later than training window.
5. The UI never invents metrics, costs, savings, weather, carbon factors, or building metadata.
6. Upload has schema validation and safe limits; API does not read arbitrary filesystem paths.
7. Tests cover feature engineering, leakage, missing data, flatline detection, event grouping, excess-kWh math, feedback validation, and core endpoints.
8. CI runs tests and frontend build. Docker images build successfully if Docker is available.
9. All downloaded datasets are kept out of Git, attributed, and have licence status documented.
10. At the end, provide the exact shell commands I should run, a list of files changed, results from commands actually executed, and remaining manual steps.

Begin by inspecting the repository and writing the implementation plan. Then continue implementing without waiting for my approval unless blocked by missing credentials or genuinely destructive action. Prioritize a working, tested vertical slice over superficial features. Do not remove the FastAPI + React architecture. Do not use Streamlit.
