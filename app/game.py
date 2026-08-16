"""In-memory game and turn state.

Kept deliberately small: one process, one board, one game at a time. The game
mode is pluggable (`count_up` ships first, `x01` is implemented on top of the
same turn machinery) so adding cricket later means adding a mode, not rewriting
the turn handling.
"""

from __future__ import annotations

import math
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from . import config
from .board import Score, score_point

DARTS_PER_TURN = 3

MODE_COUNT_UP = "count_up"
MODE_X01 = "x01"
GAME_MODES = (MODE_COUNT_UP, MODE_X01)


@dataclass
class Dart:
    """One scored dart, with enough provenance to debug a misread later."""

    id: str
    score: Score
    source: str  # "opencv" | "manual"
    timestamp: float
    low_confidence: bool = False

    def to_dict(self) -> dict:
        payload = self.score.to_dict()
        payload.update(
            {
                "id": self.id,
                "label": self.score.label,
                "source": self.source,
                "timestamp": self.timestamp,
                "low_confidence": self.low_confidence,
            }
        )
        return payload


@dataclass
class Player:
    name: str
    score: int = 0
    darts_thrown: int = 0
    turns: list[list[dict]] = field(default_factory=list)

    def to_dict(self) -> dict:
        average = (self.score / self.darts_thrown * 3) if self.darts_thrown else 0.0
        return {
            "name": self.name,
            "score": self.score,
            "darts_thrown": self.darts_thrown,
            "turns": self.turns,
            "three_dart_average": round(average, 2),
        }


class GameState:
    """Thread-safe holder for the current game. All mutation goes through here."""

    def __init__(self, mode: str = MODE_COUNT_UP, players: Optional[list[str]] = None, start_score: int = 501):
        self._lock = threading.RLock()
        self.reset(mode=mode, players=players, start_score=start_score)

    # --- lifecycle --------------------------------------------------------
    def reset(self, mode: str = MODE_COUNT_UP, players: Optional[list[str]] = None, start_score: int = 501) -> None:
        if mode not in GAME_MODES:
            raise ValueError(f"unknown game mode {mode!r}; expected one of {GAME_MODES}")
        with self._lock:
            self.mode = mode
            self.start_score = start_score
            names = players or ["Player 1"]
            initial = start_score if mode == MODE_X01 else 0
            self.players = [Player(name=n, score=initial) for n in names]
            self.current_player_index = 0
            self.current_turn: list[Dart] = []
            self.turn_number = 1
            self.winner: Optional[str] = None
            self.last_dart_at = 0.0
            self.warnings: list[str] = []
            self.bust = False
            # Score the active player had before this turn's first dart. Every
            # rewind (undo, manual edit, x01 bust) replays the turn from here,
            # which keeps totals correct without unwinding deltas by hand.
            self.turn_start_score = self.players[0].score

    def new_turn(self) -> None:
        """Bank the current turn and hand over to the next player."""
        with self._lock:
            player = self.current_player
            player.turns.append([d.to_dict() for d in self.current_turn])
            self.current_turn = []
            self.turn_number += 1
            self.current_player_index = (self.current_player_index + 1) % len(self.players)
            self.warnings = []
            self.bust = False
            self.turn_start_score = self.current_player.score

    # --- accessors --------------------------------------------------------
    @property
    def current_player(self) -> Player:
        return self.players[self.current_player_index]

    @property
    def turn_complete(self) -> bool:
        return len(self.current_turn) >= DARTS_PER_TURN or self.winner is not None or self.bust

    # --- scoring ----------------------------------------------------------
    def is_duplicate(self, x_mm: float, y_mm: float) -> bool:
        """Has a dart already been tallied at (roughly) this board position?

        This is what stops a dart being counted again on every subsequent frame:
        the dart stays in the board for the rest of the turn, so it keeps showing
        up in the diff, and we must recognise it as already-known.
        """
        with self._lock:
            for dart in self.current_turn:
                distance = math.hypot(dart.score.x_mm - x_mm, dart.score.y_mm - y_mm)
                if distance <= config.DUPLICATE_RADIUS_MM:
                    return True
        return False

    def add_dart_at(self, x_mm: float, y_mm: float, source: str = "opencv") -> Optional[Dart]:
        """Score a board-space point and add it to the current turn."""
        with self._lock:
            if self.turn_complete:
                return None
            score = score_point(x_mm, y_mm)
            dart = Dart(
                id=uuid.uuid4().hex[:12],
                score=score,
                source=source,
                timestamp=time.time(),
                low_confidence=score.boundary_margin_mm < config.BOUNDARY_WARN_MM,
            )
            self.current_turn.append(dart)
            self.last_dart_at = dart.timestamp
            self._apply_score(dart)
            return dart

    def _apply_score(self, dart: Dart) -> None:
        """Update the running total for the active game mode."""
        player = self.current_player
        player.darts_thrown += 1
        if self.mode == MODE_COUNT_UP:
            player.score += dart.score.points
            return

        # x01: subtract, win only on a double that lands exactly on zero, and
        # bust (score reverts to the start of the turn) on anything that would
        # leave a total below 2 or overshoot zero.
        remaining = player.score - dart.score.points
        if remaining == 0 and dart.score.multiplier == 2:
            player.score = 0
            self.winner = player.name
        elif remaining < 2:
            player.score = self.turn_start_score
            self.bust = True
            self.warnings.append(f"{player.name} bust on {dart.score.label}")
        else:
            player.score = remaining

    def undo_last_dart(self) -> Optional[Dart]:
        """Remove the most recent dart of this turn and rewind the score."""
        with self._lock:
            if not self.current_turn:
                return None
            dart = self.current_turn[-1]
            self._replay_turn(self.current_turn[:-1])
            return dart

    def edit_dart(self, dart_id: str, x_mm: float, y_mm: float) -> Optional[Dart]:
        """Replace a dart's position (used by the manual-correction UI).

        The whole turn is re-applied afterwards so x01 busts and totals stay
        consistent — cheaper and far less error-prone than patching deltas.
        """
        with self._lock:
            index = next((i for i, d in enumerate(self.current_turn) if d.id == dart_id), None)
            if index is None:
                return None
            existing = self.current_turn[index]
            replacement = Dart(
                id=existing.id,
                score=score_point(x_mm, y_mm),
                source="manual",
                timestamp=time.time(),
                low_confidence=False,
            )
            darts = list(self.current_turn)
            darts[index] = replacement
            self._replay_turn(darts)
            return replacement

    def _replay_turn(self, darts: list[Dart]) -> None:
        """Rewind to the start of the turn and re-apply the given darts."""
        player = self.current_player
        player.darts_thrown = max(0, player.darts_thrown - len(self.current_turn))
        player.score = self.turn_start_score
        self.current_turn = []
        self.winner = None
        self.bust = False
        self.warnings = []
        for dart in darts:
            self.current_turn.append(dart)
            self._apply_score(dart)

    def to_dict(self) -> dict:
        with self._lock:
            return {
                "mode": self.mode,
                "start_score": self.start_score,
                "players": [p.to_dict() for p in self.players],
                "current_player": self.current_player.name,
                "current_player_index": self.current_player_index,
                "turn_number": self.turn_number,
                "current_turn": [d.to_dict() for d in self.current_turn],
                "turn_total": sum(d.score.points for d in self.current_turn),
                "darts_remaining": max(0, DARTS_PER_TURN - len(self.current_turn)),
                "turn_complete": self.turn_complete,
                "bust": self.bust,
                "winner": self.winner,
                "warnings": list(self.warnings),
            }
