# T065 protocol: can one main meter stand in for a meter on each machine? (pre-registered)

**Written:** 2026-11-12, **before** the finder was run on the HIPE data in either window. The
protocol, the code (`backend/src/wattwise/ml/load_finder.py`, whose constants are this
protocol) and its tests are committed and pushed before the development phase runs.

**Real data:** HIPE, version 1.0.1 (KIT, CC BY 4.0; T064, D075). It has ten machines with their
own meters and the plant's main terminal, from October to December 2017. One plant: results are
evidence about it, not a guarantee for others.

## Question

Using only the main terminal's power, how well can each metered machine's **running periods**
and **energy** be found, at 10 seconds, 1 minute and 15 minutes?

**Why this question and not a bigger one.** T064 found the ten machines are 4.1 % of the main
terminal's energy. Splitting the whole plant's load cannot be scored, because 96 % of it has no
ground truth.

## What was looked at before writing this (development weeks only)

The held-out weeks were not read. On the development weeks:

- **Main terminal noise:** between consecutive 10-second bins it changes by more than 0.74 kW in
  10 % of steps, and by more than 4.7 kW in 1 %. That comes from load with no meter of its own.
- **Machine power while running:**

  | Machines | Power while running | Typical run |
  |---|---|---|
  | ChipPress | about 25 kW | 30 s |
  | HighTemperatureOven | about 3.2 kW | 4 min |
  | SolderingOven | about 3.5 kW | 30 s (thermostat cycling) |
  | WashingMachine | about 1.6 kW, peaks near 11 kW | short |
  | VacuumOven | about 1.2 kW | |
  | The two pumps, the saw, the printer, the pick-and-place unit | 0.2 to 0.9 kW | 3 to 7 hours |

- **Expectation, written down so that it can be wrong:** only machines whose steps clearly
  exceed the background changes can be found. The sub-kilowatt machines are probably invisible
  in the main terminal.

## Windows (chronological)

| Window | Local dates | UTC | Use |
|---|---|---|---|
| Development | 1 October to 12 November 2017 (6 weeks) | 2017-09-30T22:00Z to 2017-11-11T23:00Z | Machine signatures, the schedule baseline, the choice of tolerance |
| **Held-out** | 12 November 2017 to 1 January 2018 (7 weeks) | 2017-11-11T23:00Z to 2017-12-31T23:00Z | Scored **once**; `held-out` refuses a second run |

The held-out weeks include the Christmas period, so some machines may run less. That is part of
the result, not a reason to change the windows.

## What each machine is known by (development weeks only)

**Amendment to the roadmap rule** "the machine meters are used only to score":

- In the **development** weeks, each machine's own meter gives its signature. This stands in for
  what a factory knows from a nameplate or a quick measurement.
- In the **held-out** weeks, the machine meters are used only to score.

| Signature part | Definition |
|---|---|
| **Running threshold** | 10 % of its 99.9th-percentile power, and at least 0.02 kW. A machine runs in a 10-second bin when its power reaches this |
| **Running power** | The median power over its running bins: the "nameplate" stand-in |
| **Longest run** | 1.5 times its 99th-percentile run length, and at least three bins of the resolution being tested |

## The finder

For each resolution (10 s, 1 min, 15 min), on the main terminal only:

1. **Steps** are the changes between consecutive bins. A missing bin breaks the chain, so no step
   spans a gap.
2. Each step goes to the machine whose running power it is closest to (relative difference), if
   it is within that machine's **tolerance**. Otherwise it goes to no machine.
3. For each machine, a rising step opens a run and the next falling step closes it, if the run
   is no longer than the machine's longest run.
   - A second rise before a fall replaces the first.
   - A fall with nothing open is ignored.
4. A run's energy is the mean of its two step sizes times its duration.

**Tolerance** is chosen per machine and resolution on the development weeks, from 20, 30 and
40 %. The best development F1 wins; ties go to 30 %.

## Baselines

- **Never running.**
- **Schedule:** each machine's share of running time in each hour of the week (local time) in
  development. It predicts "running" in every hour slot where that share is at least 0.5.
  Energy is predicted running time times the machine's mean running power in development.
  **It reads no main-terminal data**, so the finder adds information only if it beats it.

## Scoring (held-out weeks, every resolution on the same 10-second truth)

- **Truth:** a machine is running in a 10-second bin when its own meter reaches its running
  threshold. Only bins where both the machine's meter and the main terminal have a value count.
- **Bin agreement:** precision, recall and F1 over 10-second bins. A run found at 15 minutes
  covers whole 15-minute stretches, so coarse data is judged on the same timeline.
- **Run recall:** the share of true runs touched by a predicted running bin.
- **Energy error:** predicted minus true energy, over true energy. True energy is the sum of the
  machine's own power in the held-out weeks.
- **Counter caveat:** HighTemperatureOven, PickAndPlaceUnit and ChipSaw are reported with T064's
  counter caveat.

## Acceptance (per machine and resolution, held-out, all required)

1. **F1 of at least 0.5.**
2. **At least 0.1 above the schedule baseline's F1.**
3. **Energy error within ±30 %.**

A machine and resolution that pass may be offered as "this machine's running periods, from the
main meter only" in the product (T067), with these results beside it. If nothing passes, step 4
of [PRODUCT.md](../PRODUCT.md) is not shipped and the negative result is published. All
machines, resolutions and baselines are reported, whether or not they pass.

## Not included, and why

- **Learned disaggregation models** (sequence-to-point networks, factorial hidden Markov
  models): they need training labels from the target plant, which a factory without machine
  meters does not have. The finder needs only a nameplate-like figure.
- **Reactive power and harmonics:** the main terminal records them, and they could separate
  machines with similar active power. This was left for a follow-up, to keep the first test
  simple and its answer clear.
