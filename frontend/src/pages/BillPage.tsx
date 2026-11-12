import { type ReactNode, useMemo, useState } from 'react';

import { formatShare } from '../design/format';
import { ProvenanceBadge } from '../design/Provenance';
import { PrintButton, PrintHeader } from '../design/PrintReport';
import { PageHeader } from '../design/states';
import {
  type AmountCheck,
  type Bill,
  breakdown,
  CHARGE_KINDS,
  CHARGE_LABELS,
  type ChargeKind,
  demand,
  energyCheck,
  history,
  powerFactor,
  problems,
  shiftSaving,
  timeOfDay,
  totalCheck,
  utilisation,
  validCurrency,
} from '../features/bill/bill';
import {
  cheapestContract,
  compareYear,
  type DemandRule,
  validRule,
} from '../features/bill/contract';
import { SYNTHETIC_BILL } from '../features/bill/example';

const control = 'rounded-md border border-edge bg-raised px-3 py-2 text-sm';
const TOD_ROWS = 4;
const HISTORY_ROWS = 12;

type FieldKey =
  | 'periodDays'
  | 'kwh'
  | 'kvah'
  | 'energyRate'
  | 'statedPowerFactor'
  | 'contractDemandKva'
  | 'recordedDemandKva'
  | 'billingDemandKva'
  | 'totalPayable';

interface Form {
  currency: string;
  fields: Record<FieldKey, string>;
  charges: Record<ChargeKind, string>;
  tod: { label: string; kwh: string; percent: string }[];
  history: { month: string; kwh: string; demand: string }[];
}

function emptyForm(): Form {
  return {
    currency: 'INR',
    fields: {
      periodDays: '',
      kwh: '',
      kvah: '',
      energyRate: '',
      statedPowerFactor: '',
      contractDemandKva: '',
      recordedDemandKva: '',
      billingDemandKva: '',
      totalPayable: '',
    },
    charges: Object.fromEntries(CHARGE_KINDS.map((kind) => [kind, ''])) as Record<
      ChargeKind,
      string
    >,
    tod: Array.from({ length: TOD_ROWS }, () => ({ label: '', kwh: '', percent: '' })),
    history: Array.from({ length: HISTORY_ROWS }, () => ({ month: '', kwh: '', demand: '' })),
  };
}

function text(value: number | null): string {
  return value === null ? '' : String(value);
}

function formOf(bill: Bill): Form {
  const form = emptyForm();
  return {
    currency: bill.currency,
    fields: {
      periodDays: text(bill.periodDays),
      kwh: text(bill.kwh),
      kvah: text(bill.kvah),
      energyRate: text(bill.energyRate),
      statedPowerFactor: text(bill.statedPowerFactor),
      contractDemandKva: text(bill.contractDemandKva),
      recordedDemandKva: text(bill.recordedDemandKva),
      billingDemandKva: text(bill.billingDemandKva),
      totalPayable: text(bill.totalPayable),
    },
    charges: Object.fromEntries(
      CHARGE_KINDS.map((kind) => [kind, text(bill.charges[kind])]),
    ) as Record<ChargeKind, string>,
    tod: form.tod.map((row, i) => {
      const w = bill.tod[i];
      return w ? { label: w.label, kwh: text(w.kwh), percent: text(w.percent) } : row;
    }),
    history: form.history.map((row, i) => {
      const h = bill.history[i];
      return h ? { month: h.month, kwh: text(h.kwh), demand: text(h.demandKva ?? null) } : row;
    }),
  };
}

/** A typed number, or null when the field is empty or not a number. */
function parse(value: string): number | null {
  if (value.trim() === '') return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function billOf(form: Form): Bill {
  const f = form.fields;
  return {
    currency: form.currency.trim().toUpperCase(),
    periodDays: parse(f.periodDays),
    kwh: parse(f.kwh),
    kvah: parse(f.kvah),
    contractDemandKva: parse(f.contractDemandKva),
    recordedDemandKva: parse(f.recordedDemandKva),
    billingDemandKva: parse(f.billingDemandKva),
    energyRate: parse(f.energyRate),
    statedPowerFactor: parse(f.statedPowerFactor),
    charges: Object.fromEntries(
      CHARGE_KINDS.map((kind) => [kind, parse(form.charges[kind])]),
    ) as Record<ChargeKind, number | null>,
    totalPayable: parse(f.totalPayable),
    tod: form.tod
      .filter((w) => w.label.trim() !== '' || w.kwh.trim() !== '' || w.percent.trim() !== '')
      .map((w) => ({ label: w.label.trim(), kwh: parse(w.kwh), percent: parse(w.percent) })),
    history: form.history
      .filter((h) => h.month.trim() !== '' || h.kwh.trim() !== '' || h.demand.trim() !== '')
      .map((h) => ({ month: h.month.trim(), kwh: parse(h.kwh), demandKva: parse(h.demand) })),
  };
}

// ---------------------------------------------------------------------------------------------
// Formatting
// ---------------------------------------------------------------------------------------------

function money(value: number, currency: string): string {
  return validCurrency(currency)
    ? value.toLocaleString('en', { style: 'currency', currency, maximumFractionDigits: 2 })
    : value.toLocaleString('en', { maximumFractionDigits: 2 });
}

function number(value: number, digits = 1): string {
  return value.toLocaleString('en', { maximumFractionDigits: digits });
}

function kwh(value: number): string {
  return `${number(value)} kWh`;
}

function signed(change: number): string {
  const percent = Math.round(change * 100);
  return `${percent > 0 ? '+' : percent < 0 ? '−' : ''}${String(Math.abs(percent))}%`;
}

// ---------------------------------------------------------------------------------------------
// Inputs
// ---------------------------------------------------------------------------------------------

function NumberField({
  label,
  unit,
  value,
  onChange,
  hint,
}: {
  label: string;
  unit: string;
  value: string;
  onChange: (value: string) => void;
  hint?: string;
}) {
  return (
    <label className="block text-sm">
      <span className="block font-medium">
        {label} <span className="font-normal text-muted">({unit})</span>
      </span>
      <input
        type="number"
        step="any"
        inputMode="decimal"
        value={value}
        onChange={(event) => {
          onChange(event.target.value);
        }}
        className={`${control} mt-1 w-full`}
      />
      {hint ? <span className="mt-1 block text-xs text-muted">{hint}</span> : null}
    </label>
  );
}

function Fieldset({ legend, children }: { legend: string; children: ReactNode }) {
  return (
    <fieldset className="min-w-0 space-y-3 rounded-xl border border-line bg-raised p-5">
      <legend className="px-1 font-semibold">{legend}</legend>
      {children}
    </fieldset>
  );
}

function Entry({ form, setForm }: { form: Form; setForm: (update: (f: Form) => Form) => void }) {
  const cur = validCurrency(form.currency.trim().toUpperCase())
    ? form.currency.toUpperCase()
    : 'currency';
  const field = (key: FieldKey) => ({
    value: form.fields[key],
    onChange: (value: string) => {
      setForm((f) => ({ ...f, fields: { ...f.fields, [key]: value } }));
    },
  });
  return (
    <div className="grid gap-4 lg:grid-cols-2 print:hidden">
      <Fieldset legend="Bill basics">
        <label className="block text-sm">
          <span className="block font-medium">
            Currency <span className="font-normal text-muted">(three letters)</span>
          </span>
          <input
            value={form.currency}
            maxLength={3}
            onChange={(event) => {
              const value = event.target.value.toUpperCase();
              setForm((f) => ({ ...f, currency: value }));
            }}
            className={`${control} mt-1 w-24`}
          />
        </label>
        <div className="grid gap-3 sm:grid-cols-2">
          <NumberField label="Billing period" unit="days" {...field('periodDays')} />
          <NumberField label="Energy billed" unit="kWh" {...field('kwh')} />
          <NumberField
            label="Apparent energy"
            unit="kVAh"
            hint="If the bill shows it."
            {...field('kvah')}
          />
          <NumberField label="Energy rate" unit={`${cur} per kWh`} {...field('energyRate')} />
          <NumberField
            label="Power factor, as printed"
            unit="0 to 1"
            {...field('statedPowerFactor')}
          />
        </div>
      </Fieldset>

      <Fieldset legend="Demand">
        <div className="grid gap-3 sm:grid-cols-2">
          <NumberField label="Contract demand" unit="kVA" {...field('contractDemandKva')} />
          <NumberField
            label="Recorded maximum demand"
            unit="kVA"
            hint="The highest demand the meter recorded in the period."
            {...field('recordedDemandKva')}
          />
          <NumberField
            label="Billing demand"
            unit="kVA"
            hint="The demand the fixed charge is billed on."
            {...field('billingDemandKva')}
          />
        </div>
      </Fieldset>

      <Fieldset legend="Charges, as printed">
        <p className="text-xs text-muted">
          Enter each amount as it is printed. Rebates and credits are negative.
        </p>
        <div className="grid gap-3 sm:grid-cols-2">
          {CHARGE_KINDS.map((kind) => (
            <NumberField
              key={kind}
              label={CHARGE_LABELS[kind]}
              unit={cur}
              value={form.charges[kind]}
              onChange={(value) => {
                setForm((f) => ({ ...f, charges: { ...f.charges, [kind]: value } }));
              }}
            />
          ))}
          <NumberField label="Total payable" unit={cur} {...field('totalPayable')} />
        </div>
      </Fieldset>

      <Fieldset legend="Time-of-day windows">
        <p className="text-xs text-muted">
          Each window’s consumption, and the surcharge (+) or rebate (−) your bill applies to it as
          a percentage of the energy rate. Hours outside these windows count as 0 %.
        </p>
        {form.tod.map((row, i) => {
          const n = String(i + 1);
          const set = (patch: Partial<typeof row>) => {
            setForm((f) => ({
              ...f,
              tod: f.tod.map((r, j) => (j === i ? { ...r, ...patch } : r)),
            }));
          };
          return (
            <div key={n} className="grid gap-2 sm:grid-cols-3">
              <label className="text-xs">
                Window {n} hours
                <input
                  value={row.label}
                  placeholder="e.g. 18:00–22:00"
                  onChange={(event) => {
                    set({ label: event.target.value });
                  }}
                  className={`${control} mt-1 w-full`}
                />
              </label>
              <label className="text-xs">
                Window {n} kWh
                <input
                  type="number"
                  step="any"
                  value={row.kwh}
                  onChange={(event) => {
                    set({ kwh: event.target.value });
                  }}
                  className={`${control} mt-1 w-full`}
                />
              </label>
              <label className="text-xs">
                Window {n} percent
                <input
                  type="number"
                  step="any"
                  value={row.percent}
                  onChange={(event) => {
                    set({ percent: event.target.value });
                  }}
                  className={`${control} mt-1 w-full`}
                />
              </label>
            </div>
          );
        })}
      </Fieldset>

      <Fieldset legend="Consumption in earlier months">
        <p className="text-xs text-muted">
          From the bill’s history table, in any order. Months are written as YYYY-MM. The highest
          demand (kVA) is for the contract-demand what-if, if the bills show it.
        </p>
        <div className="grid gap-2 sm:grid-cols-2">
          {form.history.map((row, i) => {
            const n = String(i + 1);
            const set = (patch: Partial<typeof row>) => {
              setForm((f) => ({
                ...f,
                history: f.history.map((r, j) => (j === i ? { ...r, ...patch } : r)),
              }));
            };
            return (
              <div key={n} className="grid grid-cols-3 gap-2">
                <label className="text-xs">
                  Month {n}
                  <input
                    value={row.month}
                    placeholder="YYYY-MM"
                    onChange={(event) => {
                      set({ month: event.target.value });
                    }}
                    className={`${control} mt-1 w-full`}
                  />
                </label>
                <label className="text-xs">
                  Month {n} kWh
                  <input
                    type="number"
                    step="any"
                    value={row.kwh}
                    onChange={(event) => {
                      set({ kwh: event.target.value });
                    }}
                    className={`${control} mt-1 w-full`}
                  />
                </label>
                <label className="text-xs">
                  Month {n} kVA
                  <input
                    type="number"
                    step="any"
                    value={row.demand}
                    onChange={(event) => {
                      set({ demand: event.target.value });
                    }}
                    className={`${control} mt-1 w-full`}
                  />
                </label>
              </div>
            );
          })}
        </div>
      </Fieldset>
    </div>
  );
}

// ---------------------------------------------------------------------------------------------
// Results
// ---------------------------------------------------------------------------------------------

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section
      aria-label={title}
      className="min-w-0 space-y-3 rounded-xl border border-line bg-raised p-5 text-sm print:break-inside-avoid"
    >
      <h3 className="text-base font-semibold">{title}</h3>
      {children}
    </section>
  );
}

function Verdict({ ok, children }: { ok: boolean; children: ReactNode }) {
  return (
    <li className="flex gap-2">
      <span className={`shrink-0 font-semibold ${ok ? 'text-observed' : 'text-synthetic'}`}>
        {ok ? 'Matches' : 'Check'}
      </span>
      <span>{children}</span>
    </li>
  );
}

function Checks({ bill }: { bill: Bill }) {
  const c = bill.currency;
  const total = totalCheck(bill);
  const energy = energyCheck(bill);
  const pf = powerFactor(bill);
  const tod = timeOfDay(bill);
  const todCheck = (name: string, check: AmountCheck | null) =>
    check === null ? null : (
      <Verdict ok={check.ok}>
        {check.ok
          ? `The ${name} matches the windows: ${money(check.expected, c)}.`
          : `The windows imply a ${name} of ${money(check.expected, c)}, but ${money(check.entered, c)} is entered. Check the windows’ kWh and percentages.`}
      </Verdict>
    );
  return (
    <Section title="Checks against the bill">
      <ul className="space-y-2">
        {total === null ? (
          <li className="text-muted">
            Enter the charges and the total payable to check that they add up.
          </li>
        ) : (
          <Verdict ok={total.ok}>
            {total.ok
              ? `The charges add up to the total payable: ${money(total.entered, c)}.`
              : `The charges add up to ${money(total.expected, c)}, but the total payable is ${money(total.entered, c)}: a difference of ${money(total.difference, c)}. Check the entries; the shares below use the charges as entered.`}
          </Verdict>
        )}
        {energy === null ? null : (
          <Verdict ok={energy.ok}>
            {energy.ok
              ? 'Energy charges equal the energy billed × the energy rate.'
              : `Energy charges differ from the energy billed × the energy rate (${money(energy.expected, c)}) by ${money(energy.difference, c)}. A tariff with slabs or extra components can explain this; otherwise check the entries.`}
          </Verdict>
        )}
        {pf.consistent === null || pf.computed === null || pf.stated === null ? null : (
          <Verdict ok={pf.consistent}>
            {pf.consistent
              ? `The printed power factor matches kWh ÷ kVAh (${number(pf.computed, 3)}).`
              : `kWh ÷ kVAh gives ${number(pf.computed, 3)}, but the printed power factor is ${number(pf.stated, 3)}.`}
          </Verdict>
        )}
        {todCheck('time-of-day surcharge', tod?.surchargeCheck ?? null)}
        {todCheck('time-of-day rebate', tod?.rebateCheck ?? null)}
      </ul>
    </Section>
  );
}

function Money({ bill }: { bill: Bill }) {
  const result = breakdown(bill);
  const c = bill.currency;
  if (result === null) return null;
  return (
    <Section title="Where the money goes">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[28rem] text-left">
          <caption className="sr-only">Charges, their share of the bill and per kWh</caption>
          <thead className="text-muted">
            <tr>
              <th scope="col" className="py-2 pr-4 font-medium">
                Charge
              </th>
              <th scope="col" className="py-2 pr-4 text-right font-medium">
                Amount
              </th>
              <th scope="col" className="py-2 pr-4 text-right font-medium">
                Share
              </th>
              <th scope="col" className="py-2 text-right font-medium">
                Per kWh
              </th>
            </tr>
          </thead>
          <tbody>
            {result.lines.map((line) => (
              <tr key={line.kind} className="border-t border-line">
                <th scope="row" className="py-2 pr-4 font-normal">
                  {CHARGE_LABELS[line.kind]}
                </th>
                <td className="py-2 pr-4 text-right tabular-nums">{money(line.amount, c)}</td>
                <td className="py-2 pr-4 text-right tabular-nums">
                  {line.share === null ? '—' : formatShare(line.share)}
                </td>
                <td className="py-2 text-right tabular-nums">
                  {line.perKwh === null ? '—' : money(line.perKwh, c)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {result.periodPerKwh === null ? null : (
        <p>
          The period’s charges come to <strong>{money(result.periodPerKwh, c)} per kWh</strong>
          {result.energyRateMultiple === null
            ? ''
            : `, ${number(result.energyRateMultiple, 2)} times the energy rate`}
          . Late payment and arrears or adjustments are not part of the period’s charges.
        </p>
      )}
    </Section>
  );
}

function DemandSection({ bill }: { bill: Bill }) {
  const d = demand(bill);
  const u = utilisation(bill);
  const c = bill.currency;
  const sentences: string[] = [];
  if (d.ratePerKva !== null) {
    sentences.push(
      `Your bill’s demand rate is ${money(d.ratePerKva, c)} per kVA for the period: every 10 kVA of billing demand costs ${money(d.ratePerKva * 10, c)}.`,
    );
  }
  if (d.billedAboveRecordedKva !== null && d.billedAboveRecordedKva > 0) {
    sentences.push(
      `You were billed on ${number(d.billedAboveRecordedKva)} kVA more than the highest demand recorded${d.billedAboveRecordedCost === null ? '' : `, which cost ${money(d.billedAboveRecordedCost, c)} this period`}.`,
    );
  } else if (d.billedAboveRecordedKva !== null) {
    sentences.push('The billing demand is not above the recorded maximum demand.');
  }
  if (d.billingShareOfContract !== null) {
    sentences.push(
      `The billing demand is ${formatShare(d.billingShareOfContract)} of the contract demand${d.recordedShareOfContract === null ? '' : `, and the recorded peak ${formatShare(d.recordedShareOfContract)}`}.`,
    );
  }
  const usage: string[] = [];
  if (u.averageKw !== null)
    usage.push(`Average load: ${number(u.averageKw)} kW over ${number(u.hours ?? 0, 0)} hours.`);
  if (u.contractUtilisation !== null) {
    usage.push(
      `Energy ÷ (contract demand × hours): ${formatShare(u.contractUtilisation)}. Utilities define load factor in different ways; this is one common definition.`,
    );
  }
  if (u.peakToAverage !== null) {
    usage.push(
      `The recorded peak is ${number(u.peakToAverage, 1)} times the average kVA: short periods of high load set the demand you pay for.`,
    );
  }
  if (!sentences.length && !usage.length) return null;
  return (
    <Section title="Demand and capacity">
      {sentences.map((s) => (
        <p key={s}>{s}</p>
      ))}
      {usage.map((s) => (
        <p key={s}>{s}</p>
      ))}
      {d.ratePerKva !== null ? (
        <p className="text-xs text-muted">
          Whether the contract demand can be changed depends on your utility’s rules and on your
          highest demand over the year; exceeding a contract demand can cost a surcharge. These are
          figures from this bill only, not a recommendation.
        </p>
      ) : null}
    </Section>
  );
}

function TimeOfDaySection({ bill }: { bill: Bill }) {
  const tod = timeOfDay(bill);
  const c = bill.currency;
  const [from, setFrom] = useState<string>('');
  const [to, setTo] = useState<string>('');
  const [amount, setAmount] = useState('1000');
  if (tod === null) return null;
  const options: { value: string; label: string }[] = [
    ...tod.rows.map((r, i) => ({
      value: String(i),
      label: `${r.label} (${r.percent === null ? '?' : `${r.percent > 0 ? '+' : ''}${String(r.percent)}%`})`,
    })),
    ...(tod.otherHoursKwh === null ? [] : [{ value: 'other', label: 'Other hours (0%)' }]),
  ];
  const side = (value: string): number | 'other' | null =>
    value === '' ? null : value === 'other' ? 'other' : Number(value);
  const fromSide = side(from);
  const toSide = side(to);
  const moved = parse(amount);
  const result =
    fromSide !== null && toSide !== null && moved !== null
      ? shiftSaving(bill, { from: fromSide, to: toSide, kwh: moved })
      : null;
  const name = (value: string) => options.find((o) => o.value === value)?.label ?? '';
  return (
    <Section title="Time of day">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[28rem] text-left">
          <caption className="sr-only">Time-of-day windows</caption>
          <thead className="text-muted">
            <tr>
              <th scope="col" className="py-2 pr-4 font-medium">
                Window
              </th>
              <th scope="col" className="py-2 pr-4 text-right font-medium">
                Energy
              </th>
              <th scope="col" className="py-2 pr-4 text-right font-medium">
                Share
              </th>
              <th scope="col" className="py-2 text-right font-medium">
                Surcharge (+) or rebate (−)
              </th>
            </tr>
          </thead>
          <tbody>
            {tod.rows.map((r, i) => (
              <tr key={`${String(i)}-${r.label}`} className="border-t border-line">
                <th scope="row" className="py-2 pr-4 font-normal">
                  {r.label}
                </th>
                <td className="py-2 pr-4 text-right tabular-nums">{kwh(r.kwh)}</td>
                <td className="py-2 pr-4 text-right tabular-nums">
                  {r.share === null ? '—' : formatShare(r.share)}
                </td>
                <td className="py-2 text-right tabular-nums">
                  {r.implied === null ? '—' : money(r.implied, c)}
                </td>
              </tr>
            ))}
            {tod.otherHoursKwh === null ? null : (
              <tr className="border-t border-line">
                <th scope="row" className="py-2 pr-4 font-normal">
                  Other hours
                </th>
                <td className="py-2 pr-4 text-right tabular-nums">{kwh(tod.otherHoursKwh)}</td>
                <td className="py-2 pr-4 text-right tabular-nums">
                  {bill.kwh ? formatShare(tod.otherHoursKwh / bill.kwh) : '—'}
                </td>
                <td className="py-2 text-right tabular-nums">{money(0, c)}</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <fieldset className="space-y-2" aria-label="Move consumption">
        <legend className="font-semibold">What if consumption moved? (hypothetical)</legend>
        <div className="flex flex-wrap items-end gap-2">
          <label className="text-xs">
            Move
            <input
              type="number"
              step="any"
              min={0}
              aria-label="kWh to move"
              value={amount}
              onChange={(event) => {
                setAmount(event.target.value);
              }}
              className={`${control} mt-1 block w-28`}
            />
          </label>
          <span className="pb-2 text-xs text-muted">kWh</span>
          <label className="text-xs">
            from
            <select
              aria-label="Move from"
              value={from}
              onChange={(event) => {
                setFrom(event.target.value);
              }}
              className={`${control} mt-1 block max-w-full`}
            >
              <option value="">Choose a window</option>
              {options.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs">
            to
            <select
              aria-label="Move to"
              value={to}
              onChange={(event) => {
                setTo(event.target.value);
              }}
              className={`${control} mt-1 block max-w-full`}
            >
              <option value="">Choose a window</option>
              {options.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </label>
        </div>
        {result === null ? (
          <p className="text-xs text-muted">
            Choose two different windows with a percentage, and an energy rate, to see the effect.
          </p>
        ) : (
          <p role="status">
            Moving {kwh(result.kwhMoved)} from {name(from)} to {name(to)} would{' '}
            {result.saving >= 0 ? 'save' : 'add'} {money(Math.abs(result.saving), c)} (
            {money(Math.abs(result.savingPerKwh), c)} per kWh)
            {result.capped ? `; capped at the ${kwh(result.kwhMoved)} that window recorded` : ''}.
            Hypothetical: it assumes the load can move and is priced the same way. A bill does not
            show demand peaks or production needs, which moving load can change.
          </p>
        )}
      </fieldset>
    </Section>
  );
}

function PowerAndPayment({ bill }: { bill: Bill }) {
  const pf = powerFactor(bill);
  const c = bill.currency;
  const line = bill.charges.powerFactor;
  const late = bill.charges.latePayment;
  const items: ReactNode[] = [];
  const shown = pf.stated ?? pf.computed;
  if (shown !== null) {
    items.push(
      <p key="pf">
        Power factor {number(shown, 3)}
        {line === null
          ? '.'
          : line < 0
            ? `: the bill gives a power-factor rebate of ${money(-line, c)}.`
            : line > 0
              ? `: the bill charges a power-factor surcharge of ${money(line, c)}.`
              : ': no power-factor surcharge or rebate on this bill.'}{' '}
        Your utility’s rules decide which power factor earns a rebate or costs a surcharge.
      </p>,
    );
  }
  if (late !== null && late > 0) {
    items.push(
      <p key="late">
        A late-payment surcharge of <strong>{money(late, c)}</strong> is on this bill. Paying by the
        due date avoids it.
      </p>,
    );
  }
  if (!items.length) return null;
  return <Section title="Power factor and payment">{items}</Section>;
}

function HistorySection({ bill }: { bill: Bill }) {
  const h = history(bill);
  if (h === null) return null;
  const largest = Math.max(...h.months.map((m) => m.kwh), 1);
  const notes: string[] = [];
  if (h.zeroMonths.length) notes.push(`No consumption in ${h.zeroMonths.join(', ')}.`);
  if (h.largestDrop) {
    notes.push(
      `Largest fall: ${signed(h.largestDrop.change)} from ${h.largestDrop.from} to ${h.largestDrop.to}.`,
    );
  }
  if (h.largestRise) {
    notes.push(
      `Largest rise: ${signed(h.largestRise.change)} from ${h.largestRise.from} to ${h.largestRise.to}.`,
    );
  }
  if (h.median !== null && h.billAgainstMedian !== null) {
    notes.push(
      `This bill’s ${kwh(bill.kwh ?? 0)} is ${signed(h.billAgainstMedian - 1)} against the median month with consumption (${kwh(h.median)}).`,
    );
  }
  return (
    <Section title="Consumption history">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[20rem] text-left">
          <caption className="sr-only">Monthly consumption, oldest first</caption>
          <thead className="text-muted">
            <tr>
              <th scope="col" className="py-1 pr-4 font-medium">
                Month
              </th>
              <th scope="col" className="py-1 pr-4 text-right font-medium">
                Energy
              </th>
              <th scope="col" className="w-1/2 py-1 font-medium">
                <span className="sr-only">Relative size</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {h.months.map((m) => (
              <tr key={m.month} className="border-t border-line">
                <th scope="row" className="py-1 pr-4 font-normal tabular-nums">
                  {m.month}
                </th>
                <td className="py-1 pr-4 text-right tabular-nums">{kwh(m.kwh)}</td>
                <td className="py-1" aria-hidden="true">
                  <div
                    className="h-2 rounded bg-accent"
                    style={{ width: `${String((m.kwh / largest) * 100)}%` }}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {notes.length ? (
        <ul className="list-disc space-y-1 pl-5">
          {notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      ) : null}
      <p className="text-xs text-muted">
        With monthly totals only, these are changes to ask about (a shutdown, a new line, a meter
        fault), not confirmed anomalies.
      </p>
    </Section>
  );
}

// ---------------------------------------------------------------------------------------------
// The contract-demand what-if (T068)
// ---------------------------------------------------------------------------------------------

interface ContractInputs {
  share: string;
  multiplier: string;
  rate: string;
  proposed: string;
}

const EMPTY_CONTRACT: ContractInputs = { share: '', multiplier: '', rate: '', proposed: '' };
/** Example rules for the synthetic bill only: made up, not any utility's. */
const EXAMPLE_CONTRACT: ContractInputs = {
  share: '75',
  multiplier: '1.5',
  rate: '',
  proposed: '300',
};

function ContractSection({
  bill,
  inputs,
  onChange,
}: {
  bill: Bill;
  inputs: ContractInputs;
  onChange: (next: ContractInputs) => void;
}) {
  const c = bill.currency;
  const derivedRate = demand(bill).ratePerKva;
  const rateText = inputs.rate.trim();
  const rate = rateText === '' ? derivedRate : parse(rateText);
  const rule: DemandRule | null =
    rate === null
      ? null
      : {
          minimumShare: (parse(inputs.share) ?? NaN) / 100,
          excessMultiplier: parse(inputs.multiplier) ?? NaN,
          ratePerKva: rate,
        };
  const current = bill.contractDemandKva;
  const proposed = parse(inputs.proposed);
  const months = bill.history.flatMap((h) =>
    /^\d{4}-(0[1-9]|1[0-2])$/.test(h.month) && h.demandKva != null && h.demandKva >= 0
      ? [{ month: h.month, demandKva: h.demandKva }]
      : [],
  );
  const missing: string[] = [];
  if (!months.length) missing.push('the highest demand (kVA) of earlier months');
  if (current === null || current <= 0) missing.push('the contract demand');
  if (rule === null || !validRule(rule)) {
    missing.push(
      'the rules: a minimum billing share (0 to 100 %), an excess multiplier (1 or more) and a demand rate',
    );
  }
  if (proposed === null || proposed <= 0) missing.push('a contract demand to try');
  const field = (key: keyof ContractInputs, label: string, unit: string, hint?: string) => (
    <label className="block">
      <span className="font-medium">{label}</span> <span className="text-muted">({unit})</span>
      <input
        type="number"
        step="any"
        min={0}
        value={inputs[key]}
        placeholder={key === 'rate' && derivedRate !== null ? String(derivedRate) : undefined}
        onChange={(event) => {
          onChange({ ...inputs, [key]: event.target.value });
        }}
        className={`${control} mt-1 block w-full`}
      />
      {hint ? <span className="mt-1 block text-xs text-muted">{hint}</span> : null}
    </label>
  );
  const ready = missing.length === 0 && rule !== null && current !== null && proposed !== null;
  const year = ready ? compareYear(months, current, proposed, rule) : null;
  const best = ready ? cheapestContract(months, rule, current) : null;
  return (
    <section
      aria-label="Contract demand what-if"
      className="min-w-0 space-y-3 rounded-xl border border-line bg-raised p-5 text-sm lg:col-span-2"
    >
      <h3 className="text-base font-semibold">Contract demand what-if (hypothetical)</h3>
      <p className="text-xs text-muted">
        Enter your tariff&rsquo;s own rules: nothing here is assumed. They are applied as: a month
        at or below the contract demand is billed on the larger of its highest demand and the
        minimum share of the contract; demand above the contract is charged at the excess multiplier
        times the demand rate. Check that this matches your tariff.
      </p>
      <div className="grid gap-3 sm:grid-cols-4">
        {field('share', 'Minimum billing demand', '% of contract')}
        {field('multiplier', 'Excess demand charged at', 'times the demand rate')}
        {field(
          'rate',
          'Demand rate',
          `${validCurrency(c) ? c : 'currency'} per kVA per month`,
          derivedRate === null ? undefined : 'Blank: the rate from this bill.',
        )}
        {field('proposed', 'Contract demand to try', 'kVA')}
      </div>
      {year === null || best === null ? (
        <p className="text-muted">To work this out, enter {missing.join('; ')}.</p>
      ) : (
        <>
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
            <dt className="text-muted">
              Demand charges, these months, now ({number(current ?? 0)} kVA)
            </dt>
            <dd className="tabular-nums">{money(year.currentTotal, c)}</dd>
            <dt className="text-muted">With {number(proposed ?? 0)} kVA</dt>
            <dd className="tabular-nums">{money(year.proposedTotal, c)}</dd>
            <dt className="text-muted">Difference</dt>
            <dd className="tabular-nums">
              {year.saving >= 0 ? 'would have saved ' : 'would have cost '}
              {money(Math.abs(year.saving), c)}
            </dd>
            <dt className="text-muted">Months above {number(proposed ?? 0)} kVA</dt>
            <dd>{year.monthsOverProposed.length ? year.monthsOverProposed.join(', ') : 'none'}</dd>
            <dt className="text-muted">Least cost under these rules</dt>
            <dd className="tabular-nums">
              {number(best.contractKva)} kVA ({money(best.total, c)}); the highest recorded demand
              was {number(year.highestKva)} kVA
            </dd>
          </dl>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[28rem] text-left">
              <caption className="sr-only">Demand charges month by month</caption>
              <thead className="text-muted">
                <tr>
                  <th scope="col" className="py-1 pr-4 font-medium">
                    Month
                  </th>
                  <th scope="col" className="py-1 pr-4 text-right font-medium">
                    Highest demand
                  </th>
                  <th scope="col" className="py-1 pr-4 text-right font-medium">
                    Now
                  </th>
                  <th scope="col" className="py-1 text-right font-medium">
                    With {number(proposed ?? 0)} kVA
                  </th>
                </tr>
              </thead>
              <tbody>
                {year.rows.map((r) => (
                  <tr key={r.month} className="border-t border-line">
                    <th scope="row" className="py-1 pr-4 font-normal tabular-nums">
                      {r.month}
                    </th>
                    <td className="py-1 pr-4 text-right tabular-nums">
                      {number(r.recordedKva)} kVA
                    </td>
                    <td className="py-1 pr-4 text-right tabular-nums">
                      {money(r.current.charge, c)}
                    </td>
                    <td className="py-1 text-right tabular-nums">
                      {money(r.proposed.charge, c)}
                      {r.proposed.excessKva > 0 ? (
                        <span className="block text-xs text-synthetic">
                          {number(r.proposed.excessKva)} kVA above the contract
                        </span>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      <p className="text-xs text-muted">
        Hypothetical: it repeats these months&rsquo; recorded demand under the rules entered. Next
        year&rsquo;s peaks may be higher, and a contract demand is changed through your
        utility&rsquo;s own procedure, notice periods and limits. This is not a recommendation.
      </p>
    </section>
  );
}

// ---------------------------------------------------------------------------------------------
// The page
// ---------------------------------------------------------------------------------------------

export function BillPage({ summary }: { summary: string }) {
  const [form, setFormState] = useState<Form>(emptyForm);
  const [fromExample, setFromExample] = useState(false);
  const [contract, setContract] = useState<ContractInputs>(EMPTY_CONTRACT);
  const bill = useMemo(() => billOf(form), [form]);
  const found = problems(bill);
  const setForm = (update: (f: Form) => Form) => {
    setFormState(update);
  };

  return (
    <>
      <PageHeader title="Bill analyser" summary={summary} />
      <PrintHeader
        title="bill"
        source={
          fromExample
            ? 'Synthetic example: made-up figures, not a real bill.'
            : 'Figures typed in from one monthly bill.'
        }
      />
      <div
        role="note"
        aria-label="How the bill analyser works"
        className="space-y-1 rounded-xl border border-line bg-sunken p-4 text-sm"
      >
        <p>
          <strong>Worked out in your browser.</strong> Nothing you enter is sent anywhere or saved;
          reloading the page clears it.
        </p>
        <p>
          A bill comes from one meter for the whole site, so it cannot show which machine uses the
          most electricity. That needs meters on the machines, or the main meter’s 15- or 30-minute
          readings, which WattWise can analyse as a meter series.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-3 print:hidden">
        <button
          type="button"
          onClick={() => {
            setFormState(formOf(SYNTHETIC_BILL));
            setFromExample(true);
            setContract(EXAMPLE_CONTRACT);
          }}
          className="rounded-md bg-accent px-4 py-2 text-sm font-semibold text-accent-ink"
        >
          Fill in a synthetic example
        </button>
        <button
          type="button"
          onClick={() => {
            setFormState(emptyForm());
            setFromExample(false);
            setContract(EMPTY_CONTRACT);
          }}
          className="rounded-md border border-edge px-4 py-2 text-sm font-semibold"
        >
          Clear
        </button>
        {fromExample ? (
          <span className="flex items-center gap-2 text-sm">
            <ProvenanceBadge kind="synthetic" />
            Made-up figures, not a real bill.
          </span>
        ) : null}
        {breakdown(bill) !== null ? <PrintButton /> : null}
      </div>

      <Entry form={form} setForm={setForm} />

      {found.length ? (
        <section
          aria-label="Entries to check"
          className="space-y-2 rounded-xl border border-line bg-raised p-5 text-sm"
        >
          <h3 className="text-base font-semibold">Entries to check</h3>
          <ul className="list-disc space-y-1 pl-5">
            {found.map((p, i) => (
              <li key={`${String(i)}-${p}`}>{p}</li>
            ))}
          </ul>
        </section>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-2">
        <Checks bill={bill} />
        <Money bill={bill} />
        <DemandSection bill={bill} />
        <TimeOfDaySection bill={bill} />
        <PowerAndPayment bill={bill} />
        <HistorySection bill={bill} />
        <ContractSection bill={bill} inputs={contract} onChange={setContract} />
      </div>
    </>
  );
}
