import { describe, expect, it, vi } from 'vitest';

import { ANALYSIS, DATASET, EVALUATION, METADATA, MODEL_METRICS } from '../test/modelFixture';
import { jsonResponse } from '../test/http';
import {
  fetchEvaluation,
  fetchMetadata,
  isAnalysisPage,
  isDatasetHealth,
  isEvaluation,
  isMetadata,
  isModelMetrics,
} from './models';

describe('model lab API contracts', () => {
  it('accepts recorded data and explicit unavailable responses', () => {
    expect(isMetadata(METADATA)).toBe(true);
    expect(isModelMetrics(MODEL_METRICS)).toBe(true);
    expect(isEvaluation(EVALUATION)).toBe(true);
    expect(isDatasetHealth(DATASET)).toBe(true);
    expect(isAnalysisPage({ items: [ANALYSIS], total: 1, limit: 10, offset: 0 })).toBe(true);
    expect(
      isMetadata({ available: false, reason: 'no_model_promoted', message: 'No model.' }),
    ).toBe(true);
  });

  it('rejects malformed nested metrics, metadata, counts and missing report scores', () => {
    expect(isMetadata({ ...METADATA, training: { meters: 'many' } })).toBe(false);
    expect(
      isModelMetrics({
        ...MODEL_METRICS,
        roles: [{ ...MODEL_METRICS.roles[1], metrics: { mae: '13' } }],
      }),
    ).toBe(false);
    expect(isEvaluation({ ...EVALUATION, baseline_metrics: null })).toBe(false);
    expect(isEvaluation({ ...EVALUATION, buildings: [{ building_id: 'bad', metrics: {} }] })).toBe(
      false,
    );
    expect(isDatasetHealth({ ...DATASET, readings: -1 })).toBe(false);
    expect(
      isAnalysisPage({
        items: [{ ...ANALYSIS, created_at: 'invalid' }],
        total: 1,
        limit: 10,
        offset: 0,
      }),
    ).toBe(false);
  });

  it('encodes building filters and pagination and forwards cancellation', async () => {
    const fetch = vi.fn().mockResolvedValue(jsonResponse(EVALUATION));
    vi.stubGlobal('fetch', fetch);
    const controller = new AbortController();
    await fetchEvaluation('A & B', 25, controller.signal);
    expect(fetch).toHaveBeenCalledWith(
      '/api/v1/models/evaluation?q=A+%26+B&limit=25&offset=25',
      expect.objectContaining({ signal: controller.signal }),
    );
  });

  it('reports malformed model responses through the shared error path', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ available: true })));
    await expect(fetchMetadata()).rejects.toMatchObject({ kind: 'invalid-response' });
  });
});
