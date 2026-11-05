"""End-to-end test with a fake core Roborock coordinator."""

from __future__ import annotations

from pathlib import Path
import struct
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_capture_events

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from custom_components.roborock_obstacle_photos.const import DOMAIN, EVENT_NEW_PHOTO

DUID = "testduid123"

# (type, photo id) for a synthetic map: four pets (type 49) and two shoes (type 2).
OBSTACLES = [(49, "001aaaaaaaaaaaaa"), (2, "002bbbbbbbbbbbbb"), (2, "003ccccccccccccc"),
             (49, "004ddddddddddddd"), (49, "005eeeeeeeeeeeee"), (49, "006fffffffffffff")]


def _synthetic_map() -> bytes:
    """A minimal Roborock map: file header, one image-like filler block, block 15."""
    header = b"rr" + struct.pack("<H", 20) + bytes(16)
    filler = struct.pack("<HHI", 2, 8, 4) + b"\x00" * 4
    records = b"".join(
        struct.pack("<HHHHHH", 1000 * i, 2000 + i, t, 9, 10, 0) + pid.encode() + bytes(8)
        for i, (t, pid) in enumerate(OBSTACLES)
    )
    block = struct.pack("<HHIH", 15, 12, len(records), len(OBSTACLES)) + bytes(2) + records
    return header + filler + block


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Allow loading the integration under test."""


def _fake_coordinator(raw: bytes):
    listeners = []

    def add_update_listener(cb):
        listeners.append(cb)
        return lambda: listeners.remove(cb)

    async def get_photo(photo_id):
        return SimpleNamespace(photo_id=photo_id, image_content=b"\xff\xd8\xff" + photo_id.encode())

    properties_api = SimpleNamespace(
        home=SimpleNamespace(add_update_listener=add_update_listener),
        map_content=SimpleNamespace(raw_api_response=raw),
        obstacle_photos=SimpleNamespace(get_photo=AsyncMock(side_effect=get_photo)),
    )
    coordinator = SimpleNamespace(
        duid=DUID,
        duid_slug=DUID,
        device_info={"name": "Qrevo Edge 3 Pro"},
        properties_api=properties_api,
        update_map=AsyncMock(),
    )
    return coordinator, listeners


async def test_saves_photos_and_creates_entities(hass: HomeAssistant, tmp_path: Path) -> None:
    """Photos from the map are fetched once, saved, announced and exposed."""
    hass.config.media_dirs = {"local": str(tmp_path)}
    coordinator, listeners = _fake_coordinator(_synthetic_map())

    roborock_entry = MockConfigEntry(domain="roborock", state=ConfigEntryState.LOADED)
    roborock_entry.add_to_hass(hass)
    roborock_entry.runtime_data = SimpleNamespace(v1=[coordinator])
    dr.async_get(hass).async_get_or_create(
        config_entry_id=roborock_entry.entry_id,
        identifiers={("roborock", DUID)},
        name="Qrevo Edge 3 Pro",
    )

    events = async_capture_events(hass, EVENT_NEW_PHOTO)
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED

    saved = sorted(tmp_path.rglob("*.jpg"))
    assert len(saved) == 6
    assert len(events) == 6
    assert sum(e.data["is_pet"] for e in events) == 4

    entities = er.async_get(hass)
    sensor_id = entities.async_get_entity_id("sensor", DOMAIN, f"{DUID}_map_obstacles")
    pet_image_id = entities.async_get_entity_id("image", DOMAIN, f"{DUID}_latest_pet_photo")
    assert entities.async_get(sensor_id).device_id is not None

    sensor = hass.states.get(sensor_id)
    assert sensor.state == "6"
    assert sensor.attributes["saved_photos"] == 6
    pet_image = hass.states.get(pet_image_id)
    assert pet_image.attributes["label"] == "pet"

    # A later map update with the same obstacles fetches nothing new.
    get_photo = coordinator.properties_api.obstacle_photos.get_photo
    calls = get_photo.await_count
    for listener in listeners:
        listener()
    await hass.async_block_till_done()
    assert get_photo.await_count == calls
    assert len(events) == 6

    # State survives a reload.
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(pet_image_id).attributes["label"] == "pet"
    assert get_photo.await_count == calls
