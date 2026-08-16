import pytest

from app import board
from app.game import MODE_COUNT_UP, MODE_X01, GameState


def throw(game, segment, ring=board.RING_OUTER_SINGLE):
    x_mm, y_mm = board.point_for_score(segment, ring)
    return game.add_dart_at(x_mm, y_mm)


def test_count_up_accumulates():
    game = GameState(mode=MODE_COUNT_UP)
    throw(game, 20, board.RING_TREBLE)
    throw(game, 20)
    throw(game, 5)
    assert game.current_player.score == 85
    assert game.turn_complete


def test_fourth_dart_is_refused_until_the_turn_is_banked():
    game = GameState(mode=MODE_COUNT_UP)
    for _ in range(3):
        throw(game, 1)
    assert throw(game, 20) is None
    game.new_turn()
    assert throw(game, 20) is not None


def test_duplicate_detection_ignores_a_dart_still_in_the_board():
    game = GameState(mode=MODE_COUNT_UP)
    x_mm, y_mm = board.point_for_score(20, board.RING_TREBLE)
    game.add_dart_at(x_mm, y_mm)
    # The same dart, seen again on the next frame a couple of mm off.
    assert game.is_duplicate(x_mm + 3, y_mm - 2)
    # A genuinely different dart nearby is not a duplicate.
    assert not game.is_duplicate(x_mm + 40, y_mm)


def test_undo_rewinds_the_score():
    game = GameState(mode=MODE_COUNT_UP)
    throw(game, 20, board.RING_TREBLE)
    throw(game, 19)
    assert game.current_player.score == 79
    removed = game.undo_last_dart()
    assert removed.score.label == "19"
    assert game.current_player.score == 60
    assert len(game.current_turn) == 1


def test_undo_with_nothing_thrown_returns_none():
    assert GameState().undo_last_dart() is None


def test_manual_edit_replaces_a_misread_dart():
    game = GameState(mode=MODE_COUNT_UP)
    dart = throw(game, 1)  # detection said 1, it was really T20
    x_mm, y_mm = board.point_for_score(20, board.RING_TREBLE)
    edited = game.edit_dart(dart.id, x_mm, y_mm)
    assert edited.score.label == "T20"
    assert game.current_player.score == 60
    assert len(game.current_turn) == 1
    assert game.current_player.darts_thrown == 1


def test_edit_unknown_dart_returns_none():
    assert GameState().edit_dart("nope", 0, 0) is None


def test_x01_subtracts_and_wins_on_a_double():
    game = GameState(mode=MODE_X01, start_score=101)
    throw(game, 20, board.RING_TREBLE)  # 101 -> 41
    assert game.current_player.score == 41
    throw(game, 9)  # 41 -> 32
    throw(game, 16, board.RING_DOUBLE)  # 32 -> 0 on a double
    assert game.current_player.score == 0
    assert game.winner == "Player 1"


def test_x01_busts_revert_to_the_turn_start_score():
    game = GameState(mode=MODE_X01, start_score=50)
    throw(game, 10)  # 50 -> 40
    throw(game, 20, board.RING_TREBLE)  # would go below zero: bust
    assert game.current_player.score == 50
    assert game.bust
    assert game.turn_complete
    assert any("bust" in w for w in game.warnings)


def test_x01_leaving_one_is_a_bust():
    game = GameState(mode=MODE_X01, start_score=20)
    throw(game, 19)
    assert game.bust
    assert game.current_player.score == 20


def test_x01_zero_without_a_double_is_a_bust():
    game = GameState(mode=MODE_X01, start_score=20)
    throw(game, 20)  # exactly zero, but on a single
    assert game.winner is None
    assert game.bust
    assert game.current_player.score == 20


def test_undo_clears_a_bust():
    game = GameState(mode=MODE_X01, start_score=50)
    throw(game, 10)
    throw(game, 20, board.RING_TREBLE)
    assert game.bust
    game.undo_last_dart()
    assert not game.bust
    assert game.current_player.score == 40


def test_players_rotate_and_turn_start_score_follows():
    game = GameState(mode=MODE_X01, players=["A", "B"], start_score=501)
    throw(game, 20, board.RING_TREBLE)
    game.new_turn()
    assert game.current_player.name == "B"
    assert game.turn_start_score == 501
    throw(game, 20)
    game.new_turn()
    assert game.current_player.name == "A"
    assert game.turn_start_score == 441


def test_low_confidence_flag_set_near_a_wire():
    game = GameState()
    # Just inside the treble ring's inner wire — half a millimetre of margin.
    x_mm, y_mm = 0.0, board.R_TREBLE_INNER + 0.3
    dart = game.add_dart_at(x_mm, y_mm)
    assert dart.low_confidence
    assert dart.score.label == "T20"


def test_turn_history_is_recorded():
    game = GameState(mode=MODE_COUNT_UP)
    throw(game, 20)
    throw(game, 20)
    throw(game, 20)
    game.new_turn()
    assert len(game.players[0].turns) == 1
    assert [d["label"] for d in game.players[0].turns[0]] == ["20", "20", "20"]


def test_unknown_mode_rejected():
    with pytest.raises(ValueError):
        GameState(mode="cricket")


def test_three_dart_average():
    game = GameState(mode=MODE_COUNT_UP)
    throw(game, 20, board.RING_TREBLE)
    throw(game, 20, board.RING_TREBLE)
    throw(game, 20, board.RING_TREBLE)
    assert game.to_dict()["players"][0]["three_dart_average"] == pytest.approx(180.0)
