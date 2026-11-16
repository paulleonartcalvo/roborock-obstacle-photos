"""Read room outlines from a raw Roborock map, for clicking rooms on the map card.

The map's image block stores one byte per 50 mm cell. A cell whose low three
bits are 7 belongs to a room, and the rest of the byte is the room (segment)
number, the same id the robot takes in app_segment_clean. Areas erased in the
app are flagged in the submap block and left out here, as the app does.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import hashlib
import struct

from .map_obstacles import _blocks

IMAGE_BLOCK = 2
SUBMAP_BLOCK = 17
CELL_MM = 50

_MAP_INSIDE = 0xFF
_MAP_SCAN = 0x07
_REMOVED = 8 | 16  # removed border, removed area
_SIMPLIFY_CELLS = 0.75  # how far (in cells) a simplified outline may stray


@dataclass(frozen=True)
class MapRoom:
    """A room's outline and a good spot for its label, in map millimetres."""

    segment: int
    outline: list[tuple[int, int]]
    label: tuple[int, int]


def rooms_digest(raw: bytes) -> str:
    """Fingerprint of the room layout (image and submap blocks), to skip re-tracing."""
    digest = hashlib.sha1()
    for block_type, block_header, data in _blocks(raw):
        if block_type in (IMAGE_BLOCK, SUBMAP_BLOCK):
            digest.update(block_header)
            digest.update(data)
    return digest.hexdigest()


def parse_rooms(raw: bytes) -> list[MapRoom]:
    """Return every room on the map, largest part only, sorted by segment id."""
    image = header = submap = None
    for block_type, block_header, data in _blocks(raw):
        if block_type == IMAGE_BLOCK:
            header, image = block_header, data
        elif block_type == SUBMAP_BLOCK:
            submap = data
    if image is None or header is None or len(header) < 16:
        return []
    top, left, height, width = struct.unpack_from("<iiii", header, len(header) - 16)
    if width <= 0 or height <= 0 or len(image) < width * height:
        return []

    cells: dict[int, set[tuple[int, int]]] = {}
    for y in range(height):
        row = y * width
        for x in range(width):
            pixel = image[row + x]
            if pixel & 0x07 != 0x07 or pixel in (_MAP_INSIDE, _MAP_SCAN):
                continue
            if submap is not None and row + x < len(submap) and submap[row + x] & _REMOVED:
                continue
            cells.setdefault(pixel >> 3, set()).add((x, y))

    rooms = []
    for segment, room_cells in sorted(cells.items()):
        part = _largest_part(room_cells)
        outline = _outline(part)
        if len(outline) < 3:
            continue
        lx, ly = _label_cell(part)
        rooms.append(
            MapRoom(
                segment=segment,
                outline=[((x + left) * CELL_MM, (y + top) * CELL_MM) for x, y in outline],
                label=(round((lx + 0.5 + left) * CELL_MM), round((ly + 0.5 + top) * CELL_MM)),
            )
        )
    return rooms


def _largest_part(cells: set[tuple[int, int]]) -> set[tuple[int, int]]:
    """The biggest 4-connected group of cells (stray specks are dropped)."""
    left = set(cells)
    best: set[tuple[int, int]] = set()
    while left:
        start = left.pop()
        part = {start}
        queue = deque([start])
        while queue:
            x, y = queue.popleft()
            for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if n in left:
                    left.remove(n)
                    part.add(n)
                    queue.append(n)
        if len(part) > len(best):
            best = part
    return best


def _outline(cells: set[tuple[int, int]]) -> list[tuple[float, float]]:
    """Outer boundary of a group of cells, traced along cell edges, then simplified."""
    # Directed edges with the room on their left; corners are cell corners.
    edges: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for x, y in cells:
        if (x, y - 1) not in cells:
            edges.setdefault((x, y), []).append((x + 1, y))
        if (x + 1, y) not in cells:
            edges.setdefault((x + 1, y), []).append((x + 1, y + 1))
        if (x, y + 1) not in cells:
            edges.setdefault((x + 1, y + 1), []).append((x, y + 1))
        if (x - 1, y) not in cells:
            edges.setdefault((x, y + 1), []).append((x, y))

    best: list[tuple[int, int]] = []
    best_area = 0.0
    while edges:
        start = next(iter(edges))
        loop = [start]
        prev, here = start, edges[start].pop()
        if not edges[start]:
            del edges[start]
        while here != start:
            loop.append(here)
            options = edges.get(here)
            if not options:
                break
            # Where two parts touch at a corner, keep turning left so the loop stays simple.
            nxt = max(options, key=lambda n: _left_turn(prev, here, n)) if len(options) > 1 else options[0]
            options.remove(nxt)
            if not options:
                del edges[here]
            prev, here = here, nxt
        area = _area(loop)
        if area > best_area:
            best, best_area = loop, area
    return _simplify(_corners(best), _SIMPLIFY_CELLS)


def _left_turn(a, b, c) -> int:
    return (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])


def _area(loop) -> float:
    return sum(
        loop[i][0] * loop[(i + 1) % len(loop)][1] - loop[(i + 1) % len(loop)][0] * loop[i][1]
        for i in range(len(loop))
    ) / 2


def _corners(loop):
    """Drop points in the middle of straight runs."""
    n = len(loop)
    return [
        loop[i]
        for i in range(n)
        if _left_turn(loop[i - 1], loop[i], loop[(i + 1) % n]) != 0
    ]


def _simplify(points, tolerance: float):
    """Douglas-Peucker on a closed outline, so stair-stepped walls become straight."""
    if len(points) < 4:
        return points
    # Split the loop at its two farthest-apart points and simplify each half.
    far = max(range(len(points)), key=lambda i: _dist_sq(points[0], points[i]))
    first = _dp(points[: far + 1], tolerance)
    second = _dp(points[far:] + [points[0]], tolerance)
    return first[:-1] + second[:-1]


def _dp(points, tolerance):
    stack = [(0, len(points) - 1)]
    keep = {0, len(points) - 1}
    while stack:
        a, b = stack.pop()
        worst, index = 0.0, None
        for i in range(a + 1, b):
            d = _segment_distance(points[i], points[a], points[b])
            if d > worst:
                worst, index = d, i
        if index is not None and worst > tolerance:
            keep.add(index)
            stack += [(a, index), (index, b)]
    return [points[i] for i in sorted(keep)]


def _dist_sq(a, b) -> float:
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2


def _segment_distance(p, a, b) -> float:
    length_sq = _dist_sq(a, b)
    if not length_sq:
        return _dist_sq(p, a) ** 0.5
    t = max(0.0, min(1.0, ((p[0] - a[0]) * (b[0] - a[0]) + (p[1] - a[1]) * (b[1] - a[1])) / length_sq))
    return _dist_sq(p, (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))) ** 0.5


def _label_cell(cells: set[tuple[int, int]]) -> tuple[int, int]:
    """The cell farthest from the room's edge, so a label sits well inside it."""
    distance = {}
    queue = deque()
    for x, y in cells:
        if any(n not in cells for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1))):
            distance[(x, y)] = 0
            queue.append((x, y))
    while queue:
        x, y = queue.popleft()
        for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if n in cells and n not in distance:
                distance[n] = distance[(x, y)] + 1
                queue.append(n)
    return max(cells, key=lambda c: (distance.get(c, 0), -c[1], -c[0]))
