from collections.abc import Iterator

import pytest
from sqlalchemy import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from wattwise.data.contracts import CANONICAL_UNIT, MeterType
from wattwise.db.migrate import upgrade
from wattwise.db.models import Building, Meter


@pytest.fixture
def session(schema_engine: Engine) -> Iterator[Session]:
    with schema_engine.begin() as connection:
        upgrade(connection)
    with Session(schema_engine) as db:
        yield db


def building(
    building_id: str = "b1",
    floor_area_m2: float | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
) -> Building:
    return Building(
        building_id=building_id,
        site_id="s1",
        timezone="Europe/London",
        floor_area_m2=floor_area_m2,
        latitude=latitude,
        longitude=longitude,
    )


def test_a_building_and_its_meters_round_trip(session: Session) -> None:
    session.add(building(floor_area_m2=1200.0, latitude=51.5, longitude=-0.1))
    session.add(
        Meter(meter_id="b1:electricity", building_id="b1", meter_type="electricity", unit="kWh")
    )
    session.commit()
    session.expire_all()

    saved = session.get(Building, "b1")
    assert saved is not None
    assert saved.floor_area_m2 == 1200.0
    assert [m.meter_id for m in saved.meters] == ["b1:electricity"]
    assert saved.created_at is not None


def test_optional_building_fields_may_be_missing(session: Session) -> None:
    session.add(building())
    session.commit()

    saved = session.get(Building, "b1")
    assert saved is not None
    assert saved.primary_use is None
    assert saved.latitude is None


@pytest.mark.parametrize(
    "bad",
    [
        building(floor_area_m2=0.0),
        building(floor_area_m2=-5.0),
        building(latitude=91.0),
        building(longitude=-181.0),
    ],
    ids=["zero-area", "negative-area", "latitude", "longitude"],
)
def test_impossible_building_values_are_rejected(session: Session, bad: Building) -> None:
    session.add(bad)

    with pytest.raises(IntegrityError):
        session.commit()


def test_a_meter_needs_an_existing_building(session: Session) -> None:
    session.add(Meter(meter_id="m1", building_id="missing", meter_type="electricity", unit="kWh"))

    with pytest.raises(IntegrityError):
        session.commit()


def test_a_building_with_meters_cannot_be_deleted(session: Session) -> None:
    session.add(building())
    session.add(Meter(meter_id="m1", building_id="b1", meter_type="electricity", unit="kWh"))
    session.commit()

    session.delete(session.get(Building, "b1"))
    with pytest.raises(IntegrityError):
        session.commit()


@pytest.mark.parametrize(
    ("meter_type", "unit"),
    [
        ("electricity", "m3"),  # the unit is not the canonical one for the type
        ("water", "kWh"),
        ("plutonium", "kWh"),  # not a meter type
        ("electricity", "BTU"),  # not a unit
    ],
)
def test_a_meter_must_use_the_contract_vocabulary_and_canonical_unit(
    session: Session, meter_type: str, unit: str
) -> None:
    session.add(building())
    session.add(Meter(meter_id="m1", building_id="b1", meter_type=meter_type, unit=unit))

    with pytest.raises(IntegrityError):
        session.commit()


def test_every_contract_meter_type_with_its_canonical_unit_is_accepted(session: Session) -> None:
    session.add(building())
    for meter_type in MeterType:
        session.add(
            Meter(
                meter_id=f"b1:{meter_type.value}",
                building_id="b1",
                meter_type=meter_type.value,
                unit=CANONICAL_UNIT[meter_type].value,
            )
        )

    session.commit()

    assert session.query(Meter).count() == len(MeterType)
