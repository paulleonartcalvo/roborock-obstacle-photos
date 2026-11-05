"""Read obstacles that have photos, and the driven path, from a raw Roborock map.

The stock map parser only reads photo ids from 28-byte obstacle records, but
newer robots (e.g. a296) use 36-byte records with the id at the same offset.
"""

from __future__ import annotations

from dataclasses import dataclass
import gzip
import struct

from .const import PET_TYPES

PATH_BLOCK = 3
OBSTACLES_WITH_PHOTO_BLOCK = 15
OTHER = "other"

_PHOTO_ID_START = 12
_PHOTO_ID_END = 28

try:
    from vacuum_map_parser_roborock.map_data_parser import RoborockMapDataParser

    _KNOWN_TYPES: dict[int, str] = dict(RoborockMapDataParser.KNOWN_OBSTACLE_TYPES)
except ImportError:  # pragma: no cover - shipped with the core integration
    _KNOWN_TYPES = {}


# Valetudo's Roborock table tells cats from dogs, and newer robots use codes
# no published table lists yet.
_LABELS: dict[int, str] = {
    **_KNOWN_TYPES,
    18: "obstacle",
    42: "obstacle",
    49: "cat",
    50: "dog",
    69: "box",  # identified from a photo taken by a Qrevo Edge 3 Pro
}


def label_for(obstacle_type: int) -> str:
    """Human readable obstacle type."""
    return _LABELS.get(obstacle_type, f"unknown ({obstacle_type})")


def category_for(obstacle_type: int) -> str:
    """Category used for filtering; cats and dogs are both "pet"."""
    if obstacle_type in PET_TYPES:
        return "pet"
    return _LABELS.get(obstacle_type, OTHER)


def obstacle_categories() -> list[str]:
    """Every selectable obstacle category, with "other" for unknown codes."""
    return [*sorted({category_for(code) for code in _LABELS}), OTHER]


@dataclass(frozen=True)
class MapObstacle:
    """An obstacle on the map that the robot photographed."""

    photo_id: str
    obstacle_type: int
    x: int
    y: int
    confidence: float | None = None

    @property
    def label(self) -> str:
        """Human readable obstacle type."""
        return label_for(self.obstacle_type)

    @property
    def category(self) -> str:
        """Category used for filtering."""
        return category_for(self.obstacle_type)


def _blocks(raw: bytes):
    """Yield (type, header, data) for each block of a raw (optionally gzipped) map."""
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    if raw[:2] != b"rr":
        raise ValueError("Not a Roborock map")
    pos = struct.unpack_from("<H", raw, 0x02)[0]
    while pos + 8 <= len(raw):
        block_type, header_len = struct.unpack_from("<HH", raw, pos)
        data_len = struct.unpack_from("<I", raw, pos + 4)[0]
        yield (
            block_type,
            raw[pos : pos + header_len],
            raw[pos + header_len : pos + header_len + data_len],
        )
        pos += header_len + data_len


def parse_obstacles_with_photo(raw: bytes) -> list[MapObstacle]:
    """Return the photographed obstacles in a raw map."""
    obstacles: list[MapObstacle] = []
    for block_type, header, data in _blocks(raw):
        if block_type == OBSTACLES_WITH_PHOTO_BLOCK:
            obstacles.extend(_parse_block(header, data))
    return obstacles


def parse_path(raw: bytes) -> list[tuple[int, int]]:
    """Return the points the robot has driven in the current or last job, in order."""
    for block_type, _header, data in _blocks(raw):
        if block_type == PATH_BLOCK:
            return [
                struct.unpack_from("<HH", data, offset)
                for offset in range(0, len(data) - 3, 4)
            ]
    return []


def _parse_block(header: bytes, data: bytes) -> list[MapObstacle]:
    count = struct.unpack_from("<H", header, 0x08)[0]
    if count == 0:
        return []
    size = len(data) // count
    if size < _PHOTO_ID_END:
        return []

    obstacles = []
    for start in range(0, count * size, size):
        x, y, obstacle_type, score, scale = struct.unpack_from("<HHHHH", data, start)
        photo_id = (
            data[start + _PHOTO_ID_START : start + _PHOTO_ID_END]
            .split(b"\x00")[0]
            .decode("ascii", "ignore")
        )
        if photo_id:
            confidence = round(score * 10 / scale) if scale else None
            obstacles.append(MapObstacle(photo_id, obstacle_type, x, y, confidence))
    return obstacles
