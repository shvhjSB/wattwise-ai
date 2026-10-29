import { describe, expect, it } from 'vitest';

import type { ExpectationPoint, MeterAlert } from '../../api/catalog';
import {
  alertView,
  defaultView,
  lastDays,
  pan,
  topAlert,
  viewDays,
  wholeSeries,
  zoomTo,
} from './view';

const START = Date.UTC(2017, 6, 1);
const HOUR = 3_600_000;

function series(hours: number): ExpectationPoint[] {
  return Array.from({ length: hours }, (_, i) => ({
    timestamp: new Date(START + i * HOUR).toISOString(),
    observed: 1,
    expected: 1,
    lower: 0,
    upper: 2,
  }));
}

function alert(startHour: number, endHour: number, score: number, id = 1): MeterAlert {
  return {
    alert_id: id,
    start: new Date(START + startHour * HOUR).toISOString(),
    end: new Date(START + endHour * HOUR).toISOString(),
    severity: 'low',
    signature: 'sustained',
    kind: 'above_expected',
    priority_score: score,
    review_status: 'unreviewed',
  };
}

describe('lastDays and wholeSeries', () => {
  it('takes the last days of a long series', () => {
    expect(lastDays(1000, 14)).toEqual({ from: 1000 - 336, to: 1000 });
  });

  it('takes all of a short series', () => {
    expect(lastDays(100, 14)).toEqual({ from: 0, to: 100 });
    expect(wholeSeries(100)).toEqual({ from: 0, to: 100 });
  });
});

describe('alertView', () => {
  const points = series(2000);

  it('shows the alert with three days either side', () => {
    expect(alertView(points, alert(500, 520, 50))).toEqual({ from: 500 - 72, to: 520 + 72 });
  });

  it('is clipped to the series at both ends', () => {
    expect(alertView(points, alert(10, 20, 50))).toEqual({ from: 0, to: 20 + 72 });
    expect(alertView(points, alert(1990, 1999, 50)).to).toBe(2000);
  });

  it('still shows something for a one-hour alert', () => {
    const view = alertView(points, alert(500, 500, 50));
    expect(view.to - view.from).toBeGreaterThan(72);
  });
});

describe('defaultView', () => {
  const points = series(2000);

  it('focuses on the highest-priority alert when there is one', () => {
    const alerts = [alert(300, 310, 20, 1), alert(900, 940, 80, 2)];

    expect(defaultView(points, alerts)).toEqual(alertView(points, alert(900, 940, 80)));
  });

  it('shows the last fortnight when there are no alerts', () => {
    expect(defaultView(points, [])).toEqual(lastDays(2000, 14));
  });
});

describe('topAlert', () => {
  it('is the highest score, or undefined for none', () => {
    expect(topAlert([alert(0, 1, 10, 1), alert(0, 1, 90, 2), alert(0, 1, 50, 3)])?.alert_id).toBe(
      2,
    );
    expect(topAlert([])).toBeUndefined();
  });
});

describe('pan', () => {
  it('moves by half the width, keeping the width', () => {
    expect(pan({ from: 100, to: 200 }, 1, 1000)).toEqual({ from: 150, to: 250 });
    expect(pan({ from: 100, to: 200 }, -1, 1000)).toEqual({ from: 50, to: 150 });
  });

  it('stops at the ends of the series without shrinking', () => {
    expect(pan({ from: 20, to: 120 }, -1, 1000)).toEqual({ from: 0, to: 100 });
    expect(pan({ from: 880, to: 980 }, 1, 1000)).toEqual({ from: 900, to: 1000 });
  });

  it('stays put when the view is the whole series', () => {
    expect(pan({ from: 0, to: 500 }, 1, 500)).toEqual({ from: 0, to: 500 });
  });
});

describe('zoomTo', () => {
  it('keeps the centre', () => {
    expect(zoomTo({ from: 400, to: 600 }, 3, 2000)).toEqual({ from: 464, to: 536 });
  });

  it('stays inside the series and never exceeds it', () => {
    expect(zoomTo({ from: 0, to: 100 }, 7, 2000)).toEqual({ from: 0, to: 168 });
    expect(zoomTo({ from: 1900, to: 2000 }, 7, 2000)).toEqual({ from: 1832, to: 2000 });
    expect(zoomTo({ from: 0, to: 100 }, 30, 200)).toEqual({ from: 0, to: 200 });
  });
});

describe('viewDays', () => {
  it('rounds to whole days, at least one', () => {
    expect(viewDays({ from: 0, to: 336 })).toBe(14);
    expect(viewDays({ from: 0, to: 5 })).toBe(1);
  });
});
