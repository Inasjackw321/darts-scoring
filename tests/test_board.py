import math

import pytest

from app import board


def polar(radius, segment):
    """Board-space point at the centre of `segment` at the given radius."""
    angle = math.radians(board.angle_for_segment(segment))
    return radius * math.cos(angle), radius * math.sin(angle)


def test_cardinal_segments_are_where_a_real_board_puts_them():
    assert board.score_point(0, 150).segment == 20  # top
    assert board.score_point(150, 0).segment == 6  # right
    assert board.score_point(0, -150).segment == 3  # bottom
    assert board.score_point(-150, 0).segment == 11  # left


def test_bulls():
    inner = board.score_point(0, 0)
    assert (inner.segment, inner.points, inner.label) == (25, 50, "BULL")
    outer = board.score_point(0, 10)
    assert (outer.segment, outer.points, outer.label) == (25, 25, "25")


def test_rings_on_the_twenty():
    assert board.score_point(*polar(60, 20)).label == "20"
    assert board.score_point(*polar(103, 20)).label == "T20"
    assert board.score_point(*polar(140, 20)).label == "20"
    assert board.score_point(*polar(166, 20)).label == "D20"


def test_off_board_is_a_miss():
    miss = board.score_point(0, board.R_DOUBLE_OUTER + 1)
    assert miss.segment == 0
    assert miss.points == 0
    assert miss.label == "MISS"


@pytest.mark.parametrize("segment", board.SEGMENT_ORDER)
def test_every_segment_round_trips(segment):
    """A point at a segment's centre must score as that segment."""
    for ring in (board.RING_INNER_SINGLE, board.RING_TREBLE, board.RING_OUTER_SINGLE, board.RING_DOUBLE):
        x, y = board.point_for_score(segment, ring)
        score = board.score_point(x, y)
        assert score.segment == segment
        assert score.ring == ring


def test_treble_twenty_scores_sixty():
    assert board.score_point(*polar(103, 20)).points == 60


def test_boundary_margin_is_large_at_a_segment_centre_and_small_at_a_wire():
    centre = board.score_point(*polar(140, 20))
    # 9 degrees at r=140 is ~22mm from the wire.
    assert centre.boundary_margin_mm > 15

    wire_angle = math.radians(board.angle_for_segment(20) - board.SEGMENT_ARC_DEG / 2 + 0.05)
    near_wire = board.score_point(140 * math.cos(wire_angle), 140 * math.sin(wire_angle))
    assert near_wire.boundary_margin_mm < 1


def test_boundary_margin_small_just_inside_the_treble_ring():
    just_inside = board.score_point(*polar(board.R_TREBLE_INNER + 0.5, 20))
    assert just_inside.ring == board.RING_TREBLE
    assert just_inside.boundary_margin_mm == pytest.approx(0.5, abs=0.01)


def test_segment_for_angle_matches_angle_for_segment():
    for segment in board.SEGMENT_ORDER:
        assert board.segment_for_angle(board.angle_for_segment(segment)) == segment
