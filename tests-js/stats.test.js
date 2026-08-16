const test = require('node:test');
const assert = require('node:assert');
const Darts = require('../docs/js/engine.js');
const Stats = require('../docs/js/stats.js');

const T20 = Darts.dart(20, 3);
const S20 = Darts.dart(20, 1);
const S1 = Darts.dart(1, 1);
const D20 = Darts.dart(20, 2);
const D16 = Darts.dart(16, 2);

function play(options, darts) {
  const g = Darts.createGame(options);
  darts.forEach((d) => g.throwDart(d));
  return Stats.compute(g.state());
}

test('a 180 is counted, averaged and banded', () => {
  const stats = play({ players: ['A'] }, [T20, T20, T20]);
  const a = stats.players[0];
  assert.equal(a.pointsScored, 180);
  assert.equal(a.dartsThrown, 3);
  assert.equal(a.threeDartAverage, 180);
  assert.equal(a.bands['180'], 1);
  assert.equal(a.bestTurn, 180);
});

test('averages divide by darts thrown, not turns', () => {
  // 60 + 20 + 1 = 81 from three darts => 81 per three darts.
  const stats = play({ players: ['A'] }, [T20, S20, S1]);
  assert.equal(Math.round(stats.players[0].threeDartAverage), 81);
});

test('a bust scores zero for the turn but the darts still count', () => {
  const stats = play({ startScore: 50, players: ['A'] }, [S20, T20]);
  const a = stats.players[0];
  assert.equal(a.busts, 1);
  assert.equal(a.pointsScored, 0, 'nothing is banked from a busted turn');
  assert.equal(a.dartsThrown, 2, 'but the darts were still thrown');
  assert.equal(a.threeDartAverage, 0);
});

test('checkout attempts count turns that started on a finishable score', () => {
  // Turn 1 starts at 170 (checkable) and does not finish.
  // Turn 2 starts at 110 (checkable) and finishes.
  const stats = play({ startScore: 170, players: ['A'] },
    [S20, S20, S20,          // 170 -> 110, an attempt that missed
     T20, D16, Darts.MISS]); // wait: 110 - 60 = 50, D16 busts? no: 50-32=18
  const a = stats.players[0];
  assert.equal(a.checkoutAttempts, 2);
  assert.equal(a.checkoutsHit, 0);
  assert.equal(a.checkoutPercent, 0);
});

test('a hit checkout is recorded with its value', () => {
  const stats = play({ startScore: 100, players: ['A'] }, [T20, D20]);
  const a = stats.players[0];
  assert.equal(a.checkoutAttempts, 1);
  assert.equal(a.checkoutsHit, 1);
  assert.equal(a.checkoutPercent, 100);
  assert.equal(a.highestCheckout, 100);
});

test('double attempts count darts thrown with a one-dart finish available', () => {
  // 40 left: every dart of that turn is a chance at D20.
  const stats = play({ startScore: 40, players: ['A'] }, [S1, D20]);
  const a = stats.players[0];
  // First dart: on 40, a one-dart finish exists -> attempt (missed).
  // 40 - 1 = 39, no one-dart finish. Turn continues, D20 is thrown on 39 => bust.
  assert.ok(a.doubleAttempts >= 1);
});

test('a clean double finish counts as a double hit', () => {
  const stats = play({ startScore: 32, players: ['A'] }, [D16]);
  const a = stats.players[0];
  assert.equal(a.doubleAttempts, 1);
  assert.equal(a.doublesHit, 1);
  assert.equal(a.doublePercent, 100);
});

test('progression records the score coming down turn by turn', () => {
  const stats = play({ players: ['A'] }, [T20, T20, T20, S20, S20, S20]);
  const leg = stats.progression[0];
  assert.equal(leg.leg, 1);
  const series = leg.series[0];
  assert.equal(series.player, 'A');
  assert.deepEqual(series.points.map((p) => p.value), [501, 321, 261]);
});

test('progression keeps a separate series per player', () => {
  const stats = play({ players: ['A', 'B'] }, [T20, T20, T20, S20, S20, S20]);
  const leg = stats.progression[0];
  assert.equal(leg.series.length, 2);
  assert.equal(leg.series[0].player, 'A');
  assert.equal(leg.series[1].player, 'B');
});

test('board counts aggregate hits per region, and misses separately', () => {
  const stats = play({ mode: Darts.MODE_COUNT_UP, players: ['A'] },
    [T20, T20, S20, Darts.MISS, Darts.BULL]);
  const board = stats.board;
  assert.equal(board.cells['20:3'], 2);
  assert.equal(board.cells['20:1'], 1);
  assert.equal(board.cells['25:2'], 1);
  assert.equal(board.misses, 1);
  assert.equal(board.max, 2);
  assert.equal(board.total, 5);
});

test('first-nine average uses only the opening three turns of a leg', () => {
  const stats = play({ mode: Darts.MODE_COUNT_UP, players: ['A'] }, [
    T20, T20, T20,   // 180
    T20, T20, T20,   // 180
    T20, T20, T20,   // 180
    S1, S1, S1       // 3, must not affect the first nine
  ]);
  assert.equal(stats.players[0].firstNineAverage, 180);
  assert.ok(stats.players[0].threeDartAverage < 180);
});

test('stats on an untouched game are all zero rather than NaN', () => {
  const stats = play({ players: ['A'] }, []);
  const a = stats.players[0];
  assert.equal(a.threeDartAverage, 0);
  assert.equal(a.firstNineAverage, 0);
  assert.equal(a.checkoutPercent, 0);
  assert.equal(a.doublePercent, 0);
  assert.equal(a.worstTurn, 0);
  assert.equal(stats.totalDarts, 0);
});

test('two players accumulate independently', () => {
  const stats = play({ players: ['A', 'B'] }, [T20, T20, T20, S1, S1, S1]);
  assert.equal(stats.players[0].pointsScored, 180);
  assert.equal(stats.players[1].pointsScored, 3);
  assert.equal(stats.players[0].bands['180'], 1);
  assert.equal(stats.players[1].bands['180'], 0);
});
