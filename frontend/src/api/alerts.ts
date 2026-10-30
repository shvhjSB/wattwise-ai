import { getJson, postJson } from './client';
import type { Page } from './catalog';
import type { StoredKind } from './summary';

export const SEVERITIES = ['high', 'medium', 'low'] as const;
export const ALERT_KINDS = ['above_expected', 'below_expected', 'meter_problem'] as const;
export const REVIEW_STATUSES = [
  'unreviewed',
  'confirmed_waste',
  'expected_behaviour',
  'sensor_or_data_fault',
  'needs_investigation',
] as const;
export const FEEDBACK_LABELS = [
  'confirmed_waste',
  'expected_behaviour',
  'sensor_or_data_fault',
  'needs_investigation',
] as const;
const DATA_KINDS = ['synthetic', 'observed'] as const;

export type Severity = (typeof SEVERITIES)[number];
export type AlertKind = (typeof ALERT_KINDS)[number];
export type ReviewStatus = (typeof REVIEW_STATUSES)[number];
export type FeedbackLabel = (typeof FEEDBACK_LABELS)[number];

export interface AlertSummary {
  alert_id: number;
  meter_id: string;
  building_id: string;
  dataset_id: string;
  data_kind: StoredKind;
  detector: string;
  start: string;
  end: string;
  duration_hours: number;
  flagged_hours: number;
  direction: 'high' | 'low';
  signature: string;
  kind: AlertKind;
  severity: Severity;
  priority_score: number;
  potential_excess_kwh: number | null;
  review_status: ReviewStatus;
  reviewed_at: string | null;
  feedback_count: number;
  superseded: boolean;
}

export interface Feedback {
  feedback_id: number;
  alert_id: number;
  label: FeedbackLabel;
  note: string | null;
  reviewer: string | null;
  created_at: string;
}

export interface AlertDetail extends AlertSummary {
  model_version: string | null;
  explanation: string | null;
  evidence: Record<string, unknown>;
  feedback: Feedback[];
  caveats: string[];
  retrained_from_feedback: false;
}

export interface AlertFilters {
  building_id?: string;
  meter_id?: string;
  signature?: string;
  severity?: Severity;
  kind?: AlertKind;
  review_status?: ReviewStatus;
  start?: string;
  end?: string;
  limit?: number;
  offset?: number;
}

export interface FeedbackInput {
  label: FeedbackLabel;
  note?: string;
  reviewer?: string;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

const isString = (value: unknown): value is string => typeof value === 'string';
const isNumber = (value: unknown): value is number => typeof value === 'number';
const isNullable =
  <T>(guard: (value: unknown) => value is T) =>
  (value: unknown): value is T | null =>
    value === null || guard(value);
const oneOf = <T extends readonly unknown[]>(values: T, value: unknown): value is T[number] =>
  values.includes(value);

export function isAlertSummary(value: unknown): value is AlertSummary {
  return (
    isRecord(value) &&
    isNumber(value.alert_id) &&
    isString(value.meter_id) &&
    isString(value.building_id) &&
    isString(value.dataset_id) &&
    oneOf(DATA_KINDS, value.data_kind) &&
    isString(value.detector) &&
    isString(value.start) &&
    isString(value.end) &&
    isNumber(value.duration_hours) &&
    isNumber(value.flagged_hours) &&
    (value.direction === 'high' || value.direction === 'low') &&
    isString(value.signature) &&
    oneOf(ALERT_KINDS, value.kind) &&
    oneOf(SEVERITIES, value.severity) &&
    isNumber(value.priority_score) &&
    isNullable(isNumber)(value.potential_excess_kwh) &&
    oneOf(REVIEW_STATUSES, value.review_status) &&
    isNullable(isString)(value.reviewed_at) &&
    isNumber(value.feedback_count) &&
    typeof value.superseded === 'boolean'
  );
}

export function isFeedback(value: unknown): value is Feedback {
  return (
    isRecord(value) &&
    isNumber(value.feedback_id) &&
    isNumber(value.alert_id) &&
    oneOf(FEEDBACK_LABELS, value.label) &&
    isNullable(isString)(value.note) &&
    isNullable(isString)(value.reviewer) &&
    isString(value.created_at)
  );
}

export function isAlertDetail(value: unknown): value is AlertDetail {
  if (!isAlertSummary(value)) return false;
  const detail = value as AlertSummary & Record<string, unknown>;
  return (
    isNullable(isString)(detail.model_version) &&
    isNullable(isString)(detail.explanation) &&
    isRecord(detail.evidence) &&
    Array.isArray(detail.feedback) &&
    detail.feedback.every(isFeedback) &&
    Array.isArray(detail.caveats) &&
    detail.caveats.every(isString) &&
    detail.retrained_from_feedback === false
  );
}

function isAlertPage(value: unknown): value is Page<AlertSummary> {
  return (
    isRecord(value) &&
    Array.isArray(value.items) &&
    value.items.every(isAlertSummary) &&
    isNumber(value.total) &&
    isNumber(value.limit) &&
    isNumber(value.offset)
  );
}

export function fetchAlerts(
  filters: AlertFilters,
  signal?: AbortSignal,
): Promise<Page<AlertSummary>> {
  const query = new URLSearchParams();
  for (const [name, value] of Object.entries(filters)) {
    if (value !== undefined && value !== '') query.set(name, String(value));
  }
  return getJson(`/api/v1/alerts?${query.toString()}`, isAlertPage, signal ? { signal } : {});
}

export function fetchAlert(alertId: number, signal?: AbortSignal): Promise<AlertDetail> {
  return getJson(`/api/v1/alerts/${String(alertId)}`, isAlertDetail, signal ? { signal } : {});
}

export function addAlertFeedback(
  alertId: number,
  body: FeedbackInput,
  signal?: AbortSignal,
): Promise<Feedback> {
  return postJson(
    `/api/v1/alerts/${String(alertId)}/feedback`,
    body,
    isFeedback,
    signal ? { signal } : {},
  );
}
