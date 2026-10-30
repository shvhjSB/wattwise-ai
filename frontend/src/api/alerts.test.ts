import { describe, expect, it, vi } from 'vitest';

import { alertDetail, alertSummary, feedback } from '../test/alertFixture';
import { jsonResponse } from '../test/http';
import { addAlertFeedback, fetchAlert, fetchAlerts } from './alerts';
import { ApiError } from './client';

describe('alerts API', () => {
  it('validates a filtered page and encodes its query', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse({ items: [alertSummary()], total: 1, limit: 25, offset: 0 }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(
      fetchAlerts({ severity: 'high', building_id: 'B 1', limit: 25, offset: 0 }),
    ).resolves.toMatchObject({ total: 1 });
    expect(fetchMock.mock.calls[0]?.[0]).toContain('severity=high&building_id=B+1');
  });

  it('validates an alert detail and rejects a partial summary', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(alertDetail())));
    await expect(fetchAlert(1)).resolves.toMatchObject({
      alert_id: 1,
      retrained_from_feedback: false,
    });

    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(alertSummary())));
    await expect(fetchAlert(1)).rejects.toMatchObject({
      kind: 'invalid-response',
    } satisfies Partial<ApiError>);
  });

  it('posts reviewer feedback and validates the saved history item', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(feedback(), 201));
    vi.stubGlobal('fetch', fetchMock);

    await expect(
      addAlertFeedback(1, {
        label: 'needs_investigation',
        reviewer: 'ops-1',
        note: 'Check schedule.',
      }),
    ).resolves.toMatchObject({ feedback_id: 9 });
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/alerts/1/feedback',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          label: 'needs_investigation',
          reviewer: 'ops-1',
          note: 'Check schedule.',
        }),
      }),
    );
  });
});
