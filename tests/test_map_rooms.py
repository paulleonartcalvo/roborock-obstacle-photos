"""Room outlines traced from the map's cell grid."""

from __future__ import annotations

import struct

from custom_components.roborock_obstacle_photos.map_rooms import (
    CELL_MM,
    parse_rooms,
    rooms_digest,
)

TOP, LEFT = 400, 300  # where the image block sits on the map, in cells


def _raw_map(rows: list[str], removed: set[tuple[int, int]] = frozenset()) -> bytes:
    """A map whose image block is drawn from text rows, bottom row first.

    A digit is a cell of that room, '#' a wall, '.' outside.
    """
    height, width = len(rows), len(rows[0])
    image = bytearray()
    for y, row in enumerate(rows):
        for x, ch in enumerate(row):
            if ch.isdigit():
                image.append((int(ch) << 3) | 7)
            elif ch == "#":
                image.append(1)
            else:
                image.append(0)
    header = b"rr" + struct.pack("<H", 20) + bytes(16)
    image_block = struct.pack("<HHI", 2, 24, len(image)) + struct.pack("<iiii", TOP, LEFT, height, width) + bytes(image)
    submap = bytes(16 if (i % width, i // width) in removed else 0 for i in range(width * height))
    submap_block = struct.pack("<HHI", 17, 8, len(submap)) + submap
    return header + image_block + submap_block


def _mm(x: float, y: float) -> tuple[float, float]:
    return ((x + LEFT) * CELL_MM, (y + TOP) * CELL_MM)


def _scaled(rows: list[str], k: int = 3) -> list[str]:
    """Blow each cell up to k x k so real corners are bigger than the smoothing."""
    return [("".join(ch * k for ch in row)) for row in rows for _ in range(k)]


def test_rectangle_and_l_shape() -> None:
    rows = [
        "111.2222",
        "111.2222",
        "1111222.",
        "1111....",
    ]
    rooms = {room.segment: room for room in parse_rooms(_raw_map(_scaled(rows)))}
    assert set(rooms) == {1, 2}
    # Room 1: an L, traced along cell edges.
    assert set(rooms[1].outline) == {_mm(3 * x, 3 * y) for x, y in [(0, 0), (3, 0), (3, 2), (4, 2), (4, 4), (0, 4)]}
    # Room 2: the step at its corner stays.
    assert set(rooms[2].outline) == {_mm(3 * x, 3 * y) for x, y in [(4, 0), (8, 0), (8, 2), (7, 2), (7, 3), (4, 3)]}
    # Labels sit inside their room.
    lx, ly = rooms[1].label
    assert LEFT * CELL_MM < lx < (LEFT + 12) * CELL_MM
    assert TOP * CELL_MM < ly < (TOP + 12) * CELL_MM


def test_specks_erased_areas_and_holes() -> None:
    rows = [
        "33333333",
        "33#33333",
        "33333333",
        "........",
        "3.......",
    ]
    # The whole right half of row 0 was erased in the app.
    removed = {(x, y) for x in range(12, 24) for y in range(3)}
    (room,) = parse_rooms(_raw_map(_scaled(rows), removed))
    assert room.segment == 3
    # The speck at the top-left is dropped, the erased cells are cut away and
    # the wall inside is ignored (the outline is the outer edge only).
    assert set(room.outline) == {_mm(3 * x, 3 * y) for x, y in [(0, 0), (4, 0), (4, 1), (8, 1), (8, 3), (0, 3)]}


def test_diagonal_wall_is_smoothed() -> None:
    # A staircase of 1-cell steps becomes one straight edge.
    rows = ["4" * (8 - i) for i in range(8)]
    rows = [row.ljust(8, ".") for row in rows]
    (room,) = parse_rooms(_raw_map(rows))
    assert len(room.outline) <= 4


def test_digest_ignores_path_changes() -> None:
    rows = ["11", "11"]
    raw = _raw_map(rows)
    path = struct.pack("<HHIIIII", 3, 20, 4, 4, 1, 4, 0)[:20] + struct.pack("<HH", 1, 2)
    assert rooms_digest(raw) == rooms_digest(raw + path)
    assert rooms_digest(raw) != rooms_digest(_raw_map(["12", "11"]))


def test_no_image_block() -> None:
    assert parse_rooms(b"rr" + struct.pack("<H", 20) + bytes(16)) == []


def test_thin_slits_are_filled() -> None:
    # A one-cell wall poking into the room from its edge doesn't cut a slit.
    rows = [
        "5555555555",
        "5555555555",
        "5555#55555",
        "5555#55555",
        "5555#55555",
    ]
    (room,) = parse_rooms(_raw_map(rows))
    assert set(room.outline) == {_mm(*p) for p in [(0, 0), (10, 0), (10, 5), (0, 5)]}


def test_slit_filling_stays_out_of_other_rooms() -> None:
    rows = [
        "6666666666",
        "6666666666",
        "6666777777",
        "6666777777",
    ]
    rooms = {room.segment: room for room in parse_rooms(_raw_map(_scaled(rows, 2)))}
    assert set(rooms[6].outline) == {_mm(*p) for p in [(0, 0), (20, 0), (20, 4), (8, 4), (8, 8), (0, 8)]}


def test_pockets_behind_furniture_lines_belong_to_the_room() -> None:
    # Room 3's top-left corner is fenced off by a thin furniture outline but is
    # the same room (same colour), so the outline goes around it, not along it.
    rows = [
        "3333333333",
        "3333333333",
        "3333333333",
        "##########",
        "3333333333",
        "3333333333",
    ]
    (room,) = parse_rooms(_raw_map(_scaled(rows, 1)))
    assert set(room.outline) == {_mm(*p) for p in [(0, 0), (10, 0), (10, 6), (0, 6)]}


def test_pockets_are_not_joined_across_unmapped_space() -> None:
    rows = [
        "3333333333",
        "3333333333",
        "3333333333",
        "..........",
        "..........",
        "..........",
        "33333.....",
    ]
    (room,) = parse_rooms(_raw_map(rows))
    assert set(room.outline) == {_mm(*p) for p in [(0, 0), (10, 0), (10, 3), (0, 3)]}
