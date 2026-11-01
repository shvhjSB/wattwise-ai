import type {
  AnalysisRun,
  DatasetHealth,
  Evaluation,
  ModelMetadata,
  ModelMetrics,
  Metrics,
} from '../api/models';

export const MODEL_VERSION = 'fixture-model-v1';
export const METRICS: Metrics = {
  mae: 13.7,
  rmse: 76.7,
  bias: -0.54,
  wape: 0.088,
  scored: 2000,
  missing_prediction: 120,
};
export const METADATA: ModelMetadata = {
  available: true,
  version: MODEL_VERSION,
  created_at: '2026-10-27T12:00:00Z',
  serves: 'Expected consumption for analysis.',
  model: {
    name: 'fixture-lightgbm',
    family: 'lightgbm',
    variant: 'full',
    settings: { n_estimators: 50, objective: 'regression_l1' },
    seed: 0,
  },
  feature_set_version: '1',
  horizon_hours: 168,
  feature_columns: ['hour_local', 'lag_168h'],
  training: {
    data_rows: 4000,
    training_rows: 1000,
    meters: 2,
    first: '2016-01-01T00:00:00Z',
    last: '2017-06-30T23:00:00Z',
    data_fingerprint: 'fixture-only',
  },
  split: { time: { train_start: '2016-01-01T00:00:00Z' } },
  libraries: { lightgbm: '4.7.0' },
};
export const MODEL_METRICS: ModelMetrics = {
  available: true,
  version: MODEL_VERSION,
  data_label: 'observed',
  note: 'Recorded evaluation fixture; not real performance.',
  definitions: { mae: 'Mean absolute error per hourly reading.' },
  roles: [
    {
      role: 'validation',
      window_start: '2017-07-01T00:00:00Z',
      window_end: '2017-10-01T00:00:00Z',
      metrics: null,
    },
    {
      role: 'test',
      window_start: '2017-10-01T00:00:00Z',
      window_end: '2018-01-02T00:00:00Z',
      metrics: METRICS,
    },
  ],
};
export const EVALUATION: Evaluation = {
  available: true,
  version: MODEL_VERSION,
  message: 'Each forecaster uses its available predictions; row coverage differs.',
  baseline_name: 'seasonal-naive-1w',
  model_metrics: METRICS,
  baseline_metrics: { ...METRICS, mae: 15.7, scored: 2100 },
  buildings: [{ building_id: 'Building Alpha', metrics: METRICS }],
  total: 30,
  limit: 25,
  offset: 0,
};
export const DATASET: DatasetHealth = {
  dataset_id: 'fixture-dataset',
  name: 'Evaluation fixture',
  kind: 'observed',
  buildings: 2,
  meters: 2,
  readings: 4000,
  missing_values: 100,
  first_reading: '2016-01-01T00:00:00Z',
  last_reading: '2017-12-31T23:00:00Z',
};
export const ANALYSIS: AnalysisRun = {
  run_id: 7,
  created_at: '2026-10-31T12:00:00Z',
  model_version: null,
  detector: 'rolling-zscore',
  input_start: '2017-01-01T00:00:00Z',
  input_end: '2017-01-31T23:00:00Z',
  meters: 1,
  readings: 744,
  missing_values: 2,
  predictions: 0,
  alerts: 3,
};
