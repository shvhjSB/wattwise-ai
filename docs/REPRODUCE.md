# Reproducing WattWise's results

Each claim in the README, with the commands that produce it. Unless a step says otherwise, run
the commands from `backend/` with uv (see [backend/README.md](../backend/README.md)) or from
`frontend/` with npm. Data downloads are git-ignored; their checksums are in `data/manifests/`.

## Without any downloaded data

| Claim | Command | Expect |
|---|---|---|
| The browser's detector equals the server's | `uv run pytest tests/ml/test_detector_parity.py`, then `npm test -- src/features/meter/detector.test.ts` | Python's three events, matched by the TypeScript port |
| The meter check's figures on its synthetic example | `npm test -- src/features/meter` | 50,560 kWh; 120 kW peak; 16,000 kWh while closed; one 8-hour event on 21 January |
| The bill analyser and the contract what-if | `npm test -- src/features/bill src/pages/BillPage.test.tsx` | The checks against the bill's total; ₹10,27,250 at 300 kVA against ₹12,63,500; least at 267 kVA |
| The machine comparison | `uv run --env-file .env pytest tests/ml/test_machines.py tests/api/test_machines.py` | The synthetic factory's hand-worked figures (3,280 kWh, 13.23 %, 80 kWh while closed) |
| Everything, as CI runs it | Backend: `uv run --locked ruff check . && uv run --locked mypy && uv run --env-file .env pytest`. Frontend: `npm run typecheck && npm run lint && npm test && npm run build`. Browser: `uv run --env-file .env node ../frontend/scripts/e2e.mjs` | All pass |

## With downloaded data

| Claim | Data | Commands | Report |
|---|---|---|---|
| The forecasting model's test results | BDG2 (DATASETS.md) | The T051 re-score, as described in the report | [T051](reports/t051-gap-analysis.md) |
| The default detector against human labels | BDG2 raw and LEAD 1.0 (local only, D022) | `uv run python -m wattwise.ml.detector_study development ...`, then `held-out` (once) | [T054](reports/t054-detector-study.md) |
| The factory data | HIPE (CC BY 4.0) | `uv run python -m wattwise.data.hipe fetch --full`, then `prepare --archive full` | [DATASETS.md](DATASETS.md#factory-data-hipe-t064) |
| No machine breakdown from one meter | HIPE, prepared | `uv run python -m wattwise.ml.load_finder development`, then `held-out` (once) | [T065](reports/t065-load-finder-study.md) |
| The machine view on a real plant | HIPE, prepared | `uv run python -m wattwise.data.hipe canonical --archive full`, then `wattwise.db.load` (DATASETS.md) and open the Machines page for `hipe-plant` | [D077](DECISIONS.md) |

Studies marked "once" refuse to score their held-out data a second time. Their pre-registered
protocols were committed before the first run, so a re-run reproduces the result rather than
choosing it.
