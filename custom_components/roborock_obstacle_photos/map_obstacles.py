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


COVERAGE_GRID = 50  # mm between sample spots in a zone


def zone_coverage(
    points: list[tuple[int, int]], zone: list[int], reach: int
) -> float:
    """Share of ``zone`` the robot passed over, from 0 to 1.

    The zone is sampled on a 50 mm grid; a spot counts as passed over when the
    driven line came within ``reach`` mm of it (half the cleaning width).
    Map units are millimetres, as in app_zoned_clean.
    """
    x1, x2 = sorted(zone[0::2])
    y1, y2 = sorted(zone[1::2])
    xs = range(x1 + COVERAGE_GRID // 2, x2, COVERAGE_GRID) or [(x1 + x2) // 2]
    ys = range(y1 + COVERAGE_GRID // 2, y2, COVERAGE_GRID) or [(y1 + y2) // 2]
    spots = {(x, y) for x in xs for y in ys}
    total = len(spots)
    reach_sq = reach * reach

    steps = list(zip(points, points[1:])) + [(p, p) for p in points[-1:]]
    for (ax, ay), (bx, by) in steps:
        dx, dy = bx - ax, by - ay
        length_sq = dx * dx + dy * dy
        if (
            max(ax, bx) < x1 - reach
            or min(ax, bx) > x2 + reach
            or max(ay, by) < y1 - reach
            or min(ay, by) > y2 + reach
        ):
            continue
        passed = set()
        for x, y in spots:
            t = 0.0
            if length_sq:
                t = min(1.0, max(0.0, ((x - ax) * dx + (y - ay) * dy) / length_sq))
            ex, ey = ax + t * dx - x, ay + t * dy - y
            if ex * ex + ey * ey <= reach_sq:
                passed.add((x, y))
        spots -= passed
        if not spots:
            break
    return 1 - len(spots) / total
