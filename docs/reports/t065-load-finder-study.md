# T065 results: can one main meter stand in for a meter on each machine?

**Date:** 2026-11-12 · **Decision:** D076 · **Protocol:**
[t065-load-finder-protocol.md](t065-load-finder-protocol.md), committed and pushed as `55c6b0b`
before the finder was run on the data.

**Real data:** HIPE (KIT, CC BY 4.0): ten metered machines and the main terminal of one plant,
October to December 2017. Results describe that plant.

## Result

**No machine passed at any resolution, so step 4 of the product (the "big-load finder") is not
shipped.**

- On the held-out weeks the best F1 was 0.25 (SolderingOven at 10 seconds), against a pass mark
  of 0.5. Most machines scored under 0.2, and energy errors ran from −98 % to +1,982 %.
- **For the small machines that keep to a schedule, their schedule from earlier weeks beat the
  main meter:**
  - VacuumPump1: schedule F1 0.54, the finder 0.19.
  - PickAndPlaceUnit: 0.31 against 0.16.
  - ChipSaw: 0.27 against 0.08.

**What this means for the product:**

- A meter on the main incomer did **not** stand in for a meter on each machine, with this
  method, in this plant.
- Machine-level figures still need meters on the machines (step 3). WattWise will not offer a
  machine breakdown from a single meter.

## Why it failed (diagnosis on the development weeks only)

1. **The signal is there.** At the moments a machine's own power changes by at least 1 kW, the
   main terminal changes with it, and there is no clock offset between the meters.

   | Machine | Correlation of the main terminal's step with the machine's | Slope |
   |---|---|---|
   | ChipPress | 0.97 | 0.96 |
   | WashingMachine | 0.94 | 0.91 |
   | VacuumOven | 0.74 | 1.08 |
   | HighTemperatureOven | 0.64 | 0.83 |
   | SolderingOven | 0.58 | 0.74 |

2. **The machines are multi-stage, and the finder assumed one running power.**
   - ChipPress runs at about 25 kW, but its runs begin with a small step (median 2.2 kW) and
     reach full power later. Only 6 % of its runs start with a step within 30 % of 25 kW.
   - The WashingMachine is the same (2 % of its runs).

   Matching one "nameplate" power to single steps therefore misses most runs and pairs the
   wrong ones.

3. **Small machines are buried.** In 10 % of 10-second steps the main terminal changes by more
   than 0.74 kW from unmetered load alone. The 0.2 to 0.9 kW machines' steps fall inside that.
4. **Ground truth covers little of the plant.** The ten machines are 4.1 % of its energy (T064),
   so most of what moves the main terminal is unknown.

## Held-out weeks (12 November 2017 to 1 January 2018, scored once)

F1, precision and recall are over 10-second bins; energy error is (predicted − true) / true.

| Machine | Running kW | True runs | Schedule F1 | Schedule energy error | 10 s F1 | 10 s precision / recall | 10 s energy error | 1 min F1 | 1 min energy error | 15 min F1 | 15 min energy error |
|---|---|---|---|---|---|---|---|---|---|---|---|
| ChipPress | 25.15 | 656 | 0.00 | −1.00 | 0.08 | 1.00 / 0.04 | −0.97 | 0.04 | −0.98 | 0.04 | −0.98 |
| ChipSaw ¹ | 0.31 | 15 | 0.27 | +0.33 | 0.08 | 0.05 / 0.24 | +2.71 | 0.10 | +3.40 | 0.05 | +0.02 |
| HighTemperatureOven ¹ | 3.17 | 163 | 0.00 | −1.00 | 0.09 | 0.05 / 0.28 | +3.09 | 0.06 | +3.18 | 0.06 | +4.85 |
| PickAndPlaceUnit ¹ | 0.21 | 14 | 0.31 | +0.10 | 0.16 | 0.13 / 0.21 | +1.99 | 0.16 | +2.26 | 0.27 | +0.23 |
| ScreenPrinter | 0.33 | 24 | 0.23 | −0.50 | 0.16 | 0.12 / 0.25 | +1.40 | 0.16 | +1.68 | 0.07 | +0.70 |
| SolderingOven | 3.46 | 1,317 | 0.00 | −1.00 | **0.25** | 0.24 / 0.25 | −0.13 | 0.03 | +1.86 | 0.02 | +2.75 |
| VacuumOven | 1.19 | 65 | 0.00 | −1.00 | 0.02 | 0.01 / 0.23 | +19.82 | 0.01 | +15.89 | 0.00 | +4.70 |
| VacuumPump1 | 0.87 | 32 | **0.54** | +0.58 | 0.19 | 0.17 / 0.22 | +0.32 | 0.16 | +1.08 | 0.23 | +0.89 |
| VacuumPump2 | 0.78 | 9 | 0.09 | −0.81 | 0.08 | 0.05 / 0.21 | +2.36 | 0.07 | +4.77 | 0.02 | +3.79 |
| WashingMachine | 1.62 | 64 | 0.00 | −1.00 | 0.02 | 0.01 / 0.22 | +7.25 | 0.02 | +7.42 | 0.00 | +1.80 |

¹ These machines' own energy counters disagree with their measured power (T064), so their
results carry that uncertainty.

**Acceptance:**

- No machine at any resolution met F1 ≥ 0.5.
- **The closest was SolderingOven at 10 s.** It met two of the three criteria: it beat its
  schedule (0.25 against 0.00) and its energy was within 30 % (−13 %). It failed on F1.
- Every other machine and resolution met at most one criterion. For example, PickAndPlaceUnit
  at 15 min was within energy (+23 %), but its F1 (0.27) neither reached 0.5 nor beat its
  schedule (0.31).

ChipPress ran far more in the held-out weeks (656 runs) than in development (32). A schedule
learned on development cannot follow that, and neither could the finder.

## Development weeks (1 October to 12 November 2017, in-sample)

Signatures, tolerances and the schedule came from these weeks, so these figures flatter both
methods. The finder still passed nothing here. Its best development F1 was 0.51 (ChipPress at
15 min, energy error −59 %), against 0.74 for VacuumPump1's schedule.

| Machine | Schedule F1 | 10 s F1 | 1 min F1 | 15 min F1 |
|---|---|---|---|---|
| ChipPress | 0.00 | 0.00 | 0.14 | 0.51 |
| ChipSaw | 0.48 | 0.15 | 0.16 | 0.15 |
| HighTemperatureOven | 0.00 | 0.05 | 0.06 | 0.06 |
| PickAndPlaceUnit | 0.56 | 0.11 | 0.12 | 0.17 |
| ScreenPrinter | 0.46 | 0.15 | 0.14 | 0.13 |
| SolderingOven | 0.00 | 0.29 | 0.08 | 0.03 |
| VacuumOven | 0.00 | 0.03 | 0.06 | 0.00 |
| VacuumPump1 | 0.74 | 0.22 | 0.21 | 0.29 |
| VacuumPump2 | 0.11 | 0.12 | 0.09 | 0.20 |
| WashingMachine | 0.00 | 0.02 | 0.02 | 0.00 |

## What could be tried, and what it would take

These are hypotheses, not results.

- **A multi-stage finder.** Match each of a machine's typical step sizes and the sequence they
  come in, rather than one running power. Reactive power, which the main terminal also records,
  could separate machines with similar active power. The diagnosis suggests ChipPress and the
  WashingMachine are the most promising: their steps track the main terminal closely.
- **A fresh test needs fresh data.** HIPE's held-out weeks are now spent, and re-scoring them
  with a method designed after seeing these results would not be a test. A successor data set
  (22 machines, described in *Scientific Data*, 2026) could serve; its licence has not been
  checked.

## Reproduce (local data only)

```bash
cd backend
uv run python -m wattwise.data.hipe prepare --archive full     # T064
uv run python -m wattwise.ml.load_finder development           # 24 s
uv run python -m wattwise.ml.load_finder held-out              # refuses to run twice
```

Local outputs, git-ignored, in `data/processed/evaluation/load_finder/`:

| File | SHA-256 |
|---|---|
| `development.json` | `7fde307ed3b93339b54e5e2cf2e5b904517f89a5d4513daa273d44b632a7a44d` |
| `held_out.json` | `f07b4948febd5464516cf90b5cd01e08bcd9a28a96bbd91573e35f42a18b8ef1` |

The diagnosis used two scripts outside the repository that read only the development weeks;
their findings are quoted above.

## Disclosure (added in the T061 audit)

The protocol says the held-out weeks were not read. T064's data summary had already covered the
whole recording, including those weeks (for example, that the ten machines are 4.1 % of the main
terminal's energy). It did not run the load finder or look at any event on them.
