"""A small **synthetic** factory for tests (never real data): a main meter, a press, a pump and a
water meter, four weeks of hourly readings in Europe/Berlin, built so every figure is known.

- **Press:** 20 kWh in every hour from 08:00 to 16:00 local on weekdays, plus one night run of
  four hours (00:00 to 04:00 local on Wednesday 26 October 2016), which the default detector
  finds and which falls in closed hours.
- **Pump:** 2 kWh in every hour.
- **Main meter:** 30 kWh of other load plus the press and the pump.
- **Water:** 1 m3 in every hour; not electricity, so not compared.

With opening hours Monday to Friday, 06:00 to 18:00 (240 open hours of 672):

| Meter | Energy | Share of main | Running hours | Closed | Events |
|---|---|---|---|---|---|
| main | 24,784 | | 672 | 13,904 | 1 |
| press | 3,280 | 13.23 % | 164 | 80 | 1 |
| pump | 1,344 | 5.42 % | 672 | 864 | 0 |

Unmetered: 20,160 kWh, 81.34 % of the main meter.
"""

import numpy as np
import pandas as pd

from wattwise.db.load import DatasetInfo
from wattwise.db.models import DataKind

FACTORY_INFO = DatasetInfo(
    dataset_id="test-factory",
    name="Synthetic test factory (tests only)",
    kind=DataKind.SYNTHETIC,
    source="backend/tests/factory_data.py",
)
BUILDING = "test-factory"
MAIN = "test-factory:main"
PRESS = "test-factory:press"
PUMP = "test-factory:pump"
WATER = "test-factory:water"
TIMEZONE = "Europe/Berlin"
START = pd.Timestamp("2016-10-03T00:00Z")  # Monday, 02:00 local
HOURS = 28 * 24
NIGHT_RUN = pd.date_range("2016-10-25T22:00Z", periods=4, freq="h")  # 00:00-04:00 local


def factory_tables() -> tuple[pd.DataFrame, pd.DataFrame]:
    """(buildings, readings) in the canonical upload form."""
    index = pd.date_range(START, periods=HOURS, freq="h")
    local = index.tz_convert(TIMEZONE)
    working = (np.asarray(local.dayofweek) < 5) & (local.hour >= 8) & (local.hour < 16)
    press = np.where(working | index.isin(NIGHT_RUN), 20.0, 0.0)
    pump = np.full(HOURS, 2.0)
    main = 30.0 + press + pump
    stamps = index.strftime("%Y-%m-%dT%H:%M:%SZ")
    parts = [
        pd.DataFrame(
            {
                "timestamp": stamps,
                "meter_id": meter,
                "building_id": BUILDING,
                "meter_type": kind,
                "unit": unit,
                "value": values,
            }
        )
        for meter, kind, unit, values in (
            (MAIN, "electricity", "kWh", main),
            (PRESS, "electricity", "kWh", press),
            (PUMP, "electricity", "kWh", pump),
            (WATER, "water", "m3", np.ones(HOURS)),
        )
    ]
    buildings = pd.DataFrame(
        {"building_id": [BUILDING], "site_id": ["test-site"], "timezone": [TIMEZONE]}
    )
    return buildings, pd.concat(parts, ignore_index=True)
