# Product focus: the electricity check-up for small factories

**Decided:** 2026-11-11 (D074, owner request: "unique, and solving a major real problem that is
common and not solved"). This page states the problem, what already exists, what WattWise will
claim, and what it will not. The roadmap's M14 follows from it.

## The problem

A small or medium factory pays for electricity through a bill it cannot easily decode, and it
cannot see which machines or hours waste energy.

- **The bill.** An industrial bill mixes energy charges, demand charges, time-of-day surcharges,
  power-factor adjustments, fuel surcharges, duty and late fees. Rules differ by state and
  utility.
- **The machines.** Knowing what each machine uses needs a meter on each machine. That costs
  money every month, so most small plants have one meter for the whole site.
- **The help available.** Energy audits happen once and cost money. India's Bureau of Energy
  Efficiency lists high transaction costs, perceived technology risk and limited capital as the
  barriers for small enterprises.

## What already exists (checked 2026-11-11)

| What | Who | What it means for WattWise |
|---|---|---|
| Free bill tracking that flags power-factor penalties and demand overshoot from typed-in bills; per-machine IoT meters at ₹299 to ₹1,499 per meter per month; site bundles at ₹2,500 to ₹5,000 per month | VoltSpark (India) | **A bill checker alone is not unique.** Per-machine visibility is sold as hardware with a monthly fee |
| Energy audits and power-factor services | Consultants | One-off and paid |
| Interval-data viewers and libraries | meterdatalogic (open source, Python), Solar Proof (free viewer, Australia), Energy Lens (commercial) | Analysing a meter file is not new either; none targets Indian tariffs |
| A tool that re-computes Indian HT bills from tariff orders | None found in one search | Not proof that none exists |

This was one round of searching, not a market study. "None found" means exactly that.

## What WattWise will be

**A free, private electricity check-up for a small factory, from the data it already has.**

| Step | Data needed | What it gives | Status |
|---|---|---|---|
| 1. Bill check | The monthly bill, typed in | Where the money goes, the demand charge, time-of-day and power-factor effects, late fees, checked against the bill's own total | Built (T062) |
| 2. Meter check | The main meter's interval file (15, 30 or 60 minutes) | When the peak demand happens, consumption while the plant is closed, unusual days | Planned (T067) |
| 3. Machine view | A meter on each machine | Which machine uses what, and each machine's unusual hours | Planned (T066), shown on real factory data |
| 4. Big-load finder | The main meter only, at fine resolution | The plant's large loads and their running hours, **as estimates** | **Research (T065): shipped only if it passes its test** |

### What makes it different (each point must stay true)

1. **Private by design.** The bill check and the meter check run in the browser. There is no
   account, and nothing is uploaded or stored. Competing platforms keep the customer's data.
2. **Evidence first.** Every method is published with its measured accuracy on real data,
   including where it fails (for example T054: the default detector finds 26 % of human-labelled
   anomalies on held-out data).
3. **The unsolved part, tested rather than promised.** Step 4 asks whether one meter on the main
   incomer can stand in for a meter on every machine. The study measures it on a real factory
   with ground truth, at 5 seconds, 1 minute and 15 minutes, with criteria fixed in advance. If
   it works at some resolution, one logger replaces ten meters. If it does not, WattWise says so
   and step 3 remains the only way.

### What WattWise will not claim

- **Per-machine use from a bill.** A bill comes from one meter. No method can split it.
- **Reading any bill PDF automatically.** Layouts differ, and a misread figure makes every result
  wrong (D073).
- **Verified savings.** Potential is not verified; an anomaly is not confirmed waste.
- **That it is unique.** Only the specific differences above, each backed by a test or a source.

## Open questions that could change the plan

- **Can a factory get its meter's interval data?** India had 7.24 crore smart meters installed
  by 30 June 2026 (5.73 crore under RDSS, of 20.33 crore sanctioned; the scheme runs to
  31 March 2028). Whether a consumer can download their own 15-minute data was **not confirmed**:
  rules vary by state, and a national data-sharing framework is still a draft (June 2026). A
  plant's own panel meter or a single logger is the fallback. T067 must document what was
  actually verified.
- **Does the big-load finder work at smart-meter resolution?** Unknown until T065.

## Evidence base for steps 3 and 4

**HIPE** (High-resolution Industrial Production Energy), Karlsruhe Institute of Technology:

- **Meters:** ten machines and the main terminal of a power-electronics production plant.
- **Period:** 2017-10-01 to 2018-01-01, with a one-week subset (2017-10-23 to 2017-10-30).
- **Resolution:** reported as 5-second measurements.
- **Size:** 1.33 GB packed and 30.59 GB unpacked.
- **Licence:** CC BY 4.0.
- **Citation:** Bischof et al., "HIPE – an Energy-Status-Data Set from Industrial Production",
  ACM e-Energy 2018, <https://doi.org/10.1145/3208903.3210278>.

It is one plant in Germany over three months: results on it are evidence, not a guarantee for
other factories.

## Sources

- VoltSpark product page: <https://volt-spark.vercel.app/> (read 2026-11-11).
- HIPE data set page: <https://www.energystatusdata.kit.edu/hipe.php> (read 2026-11-11).
- BEE on MSME clusters and barriers (via search summary, not read in full):
  <https://iea.blob.core.windows.net/assets/imports/events/131/SameerPandita.pdf>.
- Smart-meter counts (via search summary of a Parliament reply):
  <https://www.tndindia.com/indias-smart-meter-population-at-7-24-crore-parliament/amp/>.
- Draft National Electricity Data Sharing Framework 2026 (via search summary):
  <https://images.assettype.com/downtoearth/2026-07-02/vyxv2grj/draft_National_Electricity_Data_Sharing_Framework_2026__June_22_2026.pdf>.
- meterdatalogic: <https://pypi.org/project/meterdatalogic/>; Solar Proof:
  <https://solarproof.com.au/free-interval-data-report.php>; Energy Lens:
  <https://www.energylens.com/interval-data>.
