# T061: Final quality audit (closes M14)

**Date:** 2026-11-12 · **Audited:** `18edb6d` (the T069 commit), plus the fixes this audit made ·
**Live site:** <https://shvhjsb.github.io/wattwise-ai/>

**Verdict.** The electricity check-up (bill check, meter check, machine view) does what its
documents say, and where it does not work, the documents now say that too. WattWise is **not
production-ready**: the server application has no authentication, so no public server is run.
What is public is a static site whose bill and meter checks run in the visitor's browser.

## How the audit was done, and what it cannot show

- **Measured checks** were run fresh on this commit: tests, lint, types, formatting, build,
  link check, the browser suite, the CI run and the live site. Nothing here is copied from an
  earlier task's claim.
- **A separate reviewer read every claim** in the README, product page, home page, reports and
  records against the code and the saved results. It reported 11 findings. Each was checked
  against the files before being acted on.
- **The security review was done by me, not by an independent reviewer.** The reviewer agent
  stopped on an API rate limit before producing anything. What follows is a targeted self-review
  of the upload, machines and privacy paths and of secrets, not a penetration test.
- **Not done:** an external audit, a screen-reader pass, a contrast measurement, load testing and
  testing with real bills from several utilities.

## Measured results

| Check | Result |
|---|---|
| Backend: lock, ruff, ruff format, strict mypy | Pass (86 packages locked, 175 files formatted, 174 source files typed) |
| Backend tests (full, with the test database) | **1,056 passed** in 7 min 22 s (before this audit's one-line test edit; the 13 machine tests were re-run after it and pass) |
| Frontend: typecheck, lint (`--max-warnings=0`), Prettier | Pass |
| Frontend tests | **370 passed** (369, plus one added by this audit) |
| Browser tests, fixture mode | **27 passed** (desktop and mobile, against a throwaway database) |
| Production build | Pass: 419.77 kB of JavaScript, 121.36 kB gzipped |
| Links in Markdown | 0 broken, across the repository's Markdown files |
| CI on `18edb6d` (run 43183702333) | All 5 jobs green |
| Dependency audit in CI | `pip-audit`: no known vulnerabilities. `npm audit`, runtime packages: 0. Full tree: 7 moderate, all one `minimatch` advisory (GHSA-g3hv-75wg-m249) reached through the `typescript-eslint` development tooling, which is not shipped |
| Secret scan in CI (gitleaks) | No leaks |
| Tracked files | No `.env`, key, database, Parquet file or file over 2 MB |
| Live site | `/` returns 200; deep links render through `404.html` (see the risks); the recorded snapshot holds 92 answers |

## What the review found, and what happened to each

| # | Severity | Finding | Outcome |
|---|---|---|---|
| 1 | High | README limitations blamed "persistence rules" for the missed short events, which T054 disproved | **Fixed** in the README; EVALUATION.md marked superseded |
| 2 | Medium | The 26.4 % detector figure had no basis | **Fixed**: held-out window, 773 segments, campus buildings, 14.4 % in development, not tested on factories. T054's disclosure now says the earlier T044c check had scored a period containing the held-out window |
| 3 | Medium | "Every method is published with its tested accuracy" overclaimed | **Fixed** on the home page and in PRODUCT.md: the detector has not been tested on factory or 15-minute data, and the Meter page now says so |
| 4 | Medium | "A single main meter cannot be split" was broader than the evidence | **Fixed** on the home, Machines and Meter pages, the machines API caveat and the README: it is the tested method, on one plant (T065), that did not work |
| 5 | Medium | **A real bug.** After filling the example and editing figures, the Bill page and its printed header still said "Synthetic example" | **Fixed**: three states (example, edited, typed). Editing the figures or the contract rules marks the report "started from the synthetic example and edited"; Clear resets it. Test added |
| 6 | Medium | EVALUATION.md called 13.700 and 13.676 the same model; 13.676 is the production refit | **Corrected** in place with a dated note |
| 7 | Low | The "scored once" guard is file-based | **Disclosed** in REPRODUCE.md. It stops accidental re-runs; it cannot prove data was never scored |
| 8 | Low | T065's "held-out weeks not read" ignored T064's whole-recording summary | **Disclosed** in the T065 study. T064 did not run the finder on those weeks |
| 9 | Low | Some evidence came from scripts outside the repository (the T065 diagnosis, the T054 delay table, the what-if check) | **Disclosed** in the README evidence table and the T065 study. Not made reproducible here |
| 10 | Low | REPRODUCE.md: a row without a command, a wrong currency format, a missing database note | **Fixed** |
| 11 | Low | Slips: the carbon figure left out 705 events with no factor; "every entry checked"; 4.0 % against 4.1 %; the status date; the M2 count; "15- or 30-minute" | **Fixed**, except that 4.0 % (hourly readings) and 4.1 % (T064) were **not reconciled**, and the roadmap says so |

The reviewer also confirmed, and the checks above agree, that the T054 and T065 code match their
pre-registered protocols and were unchanged between the protocol and the results commits, that
the arithmetic and status counts are right, and that the screens say "hypothetical" and "not
confirmed waste" where they should.

## Security review (self-review)

- **No authentication.** Anyone who can reach the server can read everything and call the three
  write endpoints (alert feedback, and the two upload routes). This is why no server is public.
  The public build sets `WATTWISE_READ_ONLY`, a middleware that refuses every request that could
  change data.
- **Request limits.** A middleware caps request size, time and concurrency. Uploads are limited
  on the bytes actually read, not on the declared length. CORS origins are an explicit list.
- **Dangerous patterns.** No unpickling (the model registry parses text and JSON after
  checking hashes). The only subprocess is `git` with a fixed argument list and no shell. A
  search found no SQL built from strings. The search was a text match, not a proof.
- **Privacy of the check-up.** The Bill and Meter code contains no network, storage or
  beacon calls (searched). The Meter page also has a test that checks the page makes no request
  beyond the shell's two, puts nothing in the address and keeps nothing in browser storage. The
  Bill page has no such test; its evidence is the search.
- **Secrets and data.** None tracked; CI's scanner found none; the owner's bill was never saved
  (tests use synthetic figures); no BDG2, LEAD or HIPE data is committed.

## Remaining risks

1. **No authentication** on the server application. Do not expose it. Fixing this was T058,
   which is deferred.
2. **Deferred tasks:** T055 (model reliability), T056, T058 (authentication) and T059 (hosted
   deployment) were replaced or deferred by D074 and are still open.
3. **The detector is untested on factories.** T054 used campus meters at hourly resolution. The
   browser port is pinned to the Python detector by a fixture, so it matches that detector, not
   necessarily real plants.
4. **One plant, one annotator.** The machine study (T065) used one factory (HIPE). The labels in
   T054 came from one annotator with unmeasured agreement.
5. **Bill accuracy on real bills is untested.** The bill check is verified against hand-worked
   synthetic figures. No real bill is stored, so tariffs from other utilities have not been
   tried; the user supplies every rule.
6. **The public Machines page is empty** until the owner approves committing a small HIPE table.
7. **Deep links on the static site return HTTP 404** while rendering through `404.html`. Visitors
   see the page; crawlers and link checkers may not.
8. **The drift endpoint times out at BDG2 scale** (T051); it is not part of the check-up.
9. **Some evidence is not in the repository** (finding 9), and the "scored once" guard is a file
   (finding 7).
10. **Accessibility and performance were not audited** beyond the tests, which query by role and
    accessible name. That shows structure, not usability. Time to process a year of 15-minute
    readings in the browser was not measured here.
11. **A development-only advisory** (`minimatch`) remains in the lint tooling.

## Open for the owner

- Whether a small hourly table derived from HIPE (CC BY 4.0, with attribution) may be committed
  so the live site can show a real factory.
- Whether to reinstate T055, T056, T058 or T059, and in what order.
- Whether a CC0 real subset joins the public demo, and whether the alert budget changes
  (D070–D072).

## Reproduce

Commands for every claim are in [REPRODUCE.md](../REPRODUCE.md). The checks in the table above:

```bash
# from backend/
uv lock --check
uv run --locked ruff check . && uv run --locked ruff format --check . && uv run --locked mypy
uv run --locked --env-file .env pytest            # needs WATTWISE_TEST_DATABASE_URL in .env
# from frontend/
npm run typecheck && npm run lint && npm run format:check && npm test && npm run build
# from backend/ (browser suite, fixture mode)
uv run --locked --env-file .env node ../frontend/scripts/e2e.mjs
```

CI runs the same checks plus `pip-audit`, `npm audit` and a secret scan on every push.
