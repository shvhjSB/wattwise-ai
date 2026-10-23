import pandas as pd
import pytest


@pytest.fixture
def readings() -> pd.DataFrame:
    """A small valid readings table with typed columns, deliberately not sorted by key."""
    return pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                [
                    "2016-01-01T01:00:00Z",
                    "2016-01-01T00:00:00Z",
                    "2016-01-01T00:00:00Z",
                    "2016-01-01T01:00:00Z",
                ],
                utc=True,
            ),
            "meter_id": ["b2:electricity", "b2:electricity", "b1:electricity", "b1:electricity"],
            "building_id": ["b2", "b2", "b1", "b1"],
            "meter_type": ["electricity"] * 4,
            "unit": ["kWh"] * 4,
            "value": [12.5, 10.0, 3.25, None],
        }
    )


@pytest.fixture
def buildings() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "building_id": ["b1", "b2"],
            "site_id": ["site-a", "site-a"],
            "timezone": ["Europe/London", "US/Eastern"],
        }
    )


@pytest.fixture
def weather() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "site_id": ["site-a", "site-a"],
            "timestamp": pd.to_datetime(["2016-01-01T00:00:00Z", "2016-01-01T01:00:00Z"], utc=True),
            "air_temperature_c": [4.5, None],
        }
    )
