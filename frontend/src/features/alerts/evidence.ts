interface Influence {
  feature: string;
  description: string | null;
  mean_value: number | null;
  mean_contribution_kwh: number;
}

export interface EvidenceView {
  detector: {
    name: string | null;
    baseline: string | null;
    observed_kwh: number | null;
    baseline_kwh: number | null;
    hours_compared: number | null;
  };
  model: {
    observed_kwh: number | null;
    expected_kwh: number | null;
    hours_with_expectation: number | null;
    interval_nominal: number | null;
    measured_coverage: number | null;
    hours_above: number | null;
    hours_below: number | null;
    agrees: boolean | null;
  };
  signature: { primary: string | null; description: string | null; all: string[] };
  influences: Influence[];
  influences_note: string | null;
  check: string | null;
}

function record(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function text(value: unknown): string | null {
  return typeof value === 'string' ? value : null;
}

function number(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function boolean(value: unknown): boolean | null {
  return typeof value === 'boolean' ? value : null;
}

export function evidenceView(bundle: Record<string, unknown>): EvidenceView {
  const detector = record(bundle.detector);
  const model = record(bundle.model);
  const interval = record(model.interval);
  const signature = record(bundle.signature);
  const rawInfluences = Array.isArray(bundle.influences) ? bundle.influences : [];
  const influences = rawInfluences.flatMap((item): Influence[] => {
    const influence = record(item);
    const feature = text(influence.feature);
    const contribution = number(influence.mean_contribution_kwh);
    if (feature === null || contribution === null) return [];
    return [
      {
        feature,
        description: text(influence.description),
        mean_value: number(influence.mean_value),
        mean_contribution_kwh: contribution,
      },
    ];
  });
  return {
    detector: {
      name: text(detector.name),
      baseline: text(detector.baseline),
      observed_kwh: number(detector.observed_kwh),
      baseline_kwh: number(detector.baseline_kwh),
      hours_compared: number(detector.hours_compared),
    },
    model: {
      observed_kwh: number(model.observed_kwh),
      expected_kwh: number(model.expected_kwh),
      hours_with_expectation: number(model.hours_with_expectation),
      interval_nominal: number(interval.nominal),
      measured_coverage: number(interval.measured_coverage_in_detection_window),
      hours_above: number(model.hours_above_upper_bound),
      hours_below: number(model.hours_below_lower_bound),
      agrees: boolean(model.agrees_with_detector),
    },
    signature: {
      primary: text(signature.primary),
      description: text(signature.description),
      all: Array.isArray(signature.all)
        ? signature.all.filter((item) => typeof item === 'string')
        : [],
    },
    influences,
    influences_note: text(bundle.influences_note),
    check: text(bundle.check),
  };
}
