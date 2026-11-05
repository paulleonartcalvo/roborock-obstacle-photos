"""Read obstacles that have photos from a raw Roborock map.

The stock map parser only reads photo ids from 28-byte obstacle records, but
newer robots (e.g. a296) use 36-byte records with the id at the same offset.
"""

from __future__ import annotations

from dataclasses import dataclass
import gzip
import struct

OBSTACLES_WITH_PHOTO_BLOCK = 15

_PHOTO_ID_START = 12
_PHOTO_ID_END = 28

try:
    from vacuum_map_parser_roborock.map_data_parser import RoborockMapDataParser

    _KNOWN_TYPES: dict[int, str] = dict(RoborockMapDataParser.KNOWN_OBSTACLE_TYPES)
except ImportError:  # pragma: no cover - shipped with the core integration
    _KNOWN_TYPES = {}


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
        return _KNOWN_TYPES.get(self.obstacle_type, f"type {self.obstacle_type}")


def parse_obstacles_with_photo(raw: bytes) -> list[MapObstacle]:
    """Return the photographed obstacles in a raw (optionally gzipped) map."""
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    if raw[:2] != b"rr":
        raise ValueError("Not a Roborock map")

    obstacles: list[MapObstacle] = []
    pos = struct.unpack_from("<H", raw, 0x02)[0]
    while pos + 8 <= len(raw):
        block_type, header_len = struct.unpack_from("<HH", raw, pos)
        data_len = struct.unpack_from("<I", raw, pos + 4)[0]
        if block_type == OBSTACLES_WITH_PHOTO_BLOCK:
            header = raw[pos : pos + header_len]
            data = raw[pos + header_len : pos + header_len + data_len]
            obstacles.extend(_parse_block(header, data))
        pos += header_len + data_len
    return obstacles


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
