from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd

DAY = timedelta(days=1)
HOUR = timedelta(hours=1)
JAN = datetime(2017, 1, 1, tzinfo=UTC)


def at(day: float) -> datetime:
    """Midnight UTC on 2017-01-(1 + day); fractions give hours."""
    return JAN + day * DAY


def readings(
    buildings: Sequence[str] = ("A", "B"), days: int = 10, freq: str = "h"
) -> pd.DataFrame:
    """Canonical electricity readings from 2017-01-01: one meter per building, regular intervals."""
    times = pd.date_range(JAN, JAN + days * DAY, freq=freq, inclusive="left").as_unit("us")
    frames = [
        pd.DataFrame(
            {
                "timestamp": times,
                "meter_id": f"{b}-electricity",
                "building_id": b,
                "meter_type": "electricity",
                "unit": "kWh",
                "value": np.arange(len(times), dtype=float),
            }
        )
        for b in buildings
    ]
    return pd.concat(frames, ignore_index=True)
