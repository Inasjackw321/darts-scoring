const test = require('node:test');
const assert = require('node:assert');
const Darts = require('../docs/js/engine.js');

const T20 = Darts.dart(20, 3);
const D20 = Darts.dart(20, 2);
const D16 = Darts.dart(16, 2);
const S20 = Darts.dart(20, 1);
const S1 = Darts.dart(1, 1);

function game(options) {
  return Darts.createGame(options);
}

function throwMany(g, darts) {
  darts.forEach((d) => g.throwDart(d));
  return g.state();
}

/* ---------------------------------------------------------------- dart values */
test('points and labels match the board', () => {
  assert.equal(Darts.points(T20), 60);
  assert.equal(Darts.points(D20), 40);
  assert.equal(Darts.points(Darts.BULL), 50);
  assert.equal(Darts.points(Darts.OUTER_BULL), 25);
  assert.equal(Darts.points(Darts.MISS), 0);

  assert.equal(Darts.label(T20), 'T20');
  assert.equal(Darts.label(D16), 'D16');
  assert.equal(Darts.label(S20), '20');
  assert.equal(Darts.label(Darts.BULL), 'Bull');
  assert.equal(Darts.label(Darts.OUTER_BULL), '25');
  assert.equal(Darts.label(Darts.MISS), 'Miss');
});

test('a bull counts as a double, an outer bull does not', () => {
  assert.equal(Darts.isDouble(Darts.BULL), true);
  assert.equal(Darts.isDouble(Darts.OUTER_BULL), false);
});

test('labels parse back into darts', () => {
  assert.deepEqual(Darts.parseLabel('T20'), T20);
  assert.deepEqual(Darts.parseLabel('d16'), D16);
  assert.deepEqual(Darts.parseLabel('20'), S20);
  assert.deepEqual(Darts.parseLabel('BULL'), Darts.BULL);
  assert.deepEqual(Darts.parseLabel('25'), Darts.OUTER_BULL);
  assert.deepEqual(Darts.parseLabel('miss'), Darts.MISS);
  assert.equal(Darts.parseLabel('T21'), null);
  assert.equal(Darts.parseLabel('hello'), null);
});

/* --------------------------------------------------------------------- x01 */
test('501 subtracts and rotates players every three darts', () => {
  const g = game({ players: ['A', 'B'] });
  const state = throwMany(g, [T20, T20, T20]);
  assert.equal(state.players[0].score, 501 - 180);
  assert.equal(state.currentPlayerIndex, 1, 'should be B to throw');
  assert.equal(state.players[0].turns[0].scored, 180);
});

test('a leg is won by landing exactly zero on a double', () => {
  const g = game({ startScore: 101, players: ['A'] });
  const state = throwMany(g, [T20, S1, D20]); // 101 - 60 - 1 - 40
  assert.equal(state.players[0].score, 0);
  assert.equal(state.matchOver, true);
  assert.equal(state.winner, 'A', 'the match winner stays readable after the win');
  assert.equal(state.players[0].legsWon, 1);
  assert.match(state.message, /wins the match/);
});

test('going below zero busts and restores the score from the start of the turn', () => {
  const g = game({ startScore: 50, players: ['A'] });
  const state = throwMany(g, [S20, T20]); // 50 -> 30, then 60 would go below zero
  assert.equal(state.players[0].score, 50);
  assert.equal(state.lastEvent, 'bust');
  assert.equal(state.currentTurn.length, 0, 'a bust ends the turn immediately');
  assert.match(state.message, /bust/);
});

test('leaving exactly one busts, because one cannot be finished on a double', () => {
  const g = game({ startScore: 21, players: ['A'] });
  const state = throwMany(g, [S20]);
  assert.equal(state.players[0].score, 21);
  assert.equal(state.lastEvent, 'bust');
});

test('hitting zero without a double busts under double-out', () => {
  const g = game({ startScore: 20, players: ['A'] });
  const state = throwMany(g, [S20]);
  assert.equal(state.players[0].score, 20);
  assert.equal(state.lastEvent, 'bust');
  assert.equal(state.matchOver, false);
});

test('double-out can be switched off for a casual game', () => {
  const g = game({ startScore: 20, players: ['A'], doubleOut: false });
  const state = throwMany(g, [S20]);
  assert.equal(state.players[0].score, 0);
  assert.equal(state.matchOver, true);
});

test('double-in ignores darts until a double lands', () => {
  const g = game({ startScore: 101, players: ['A'], doubleIn: true });
  let state = throwMany(g, [T20]);
  assert.equal(state.players[0].score, 101, 'treble does not open the leg');
  state = throwMany(g, [D20]);
  assert.equal(state.players[0].score, 61, 'the opening double counts');
  state = throwMany(g, [S20]);
  assert.equal(state.players[0].score, 41, 'and everything after it counts');
});

test('busting on the third dart still hands over correctly', () => {
  const g = game({ startScore: 60, players: ['A', 'B'] });
  const state = throwMany(g, [S20, S20, T20]); // 60->40->20, then bust
  assert.equal(state.players[0].score, 60);
  assert.equal(state.currentPlayerIndex, 1);
});

/* ------------------------------------------------------------------- legs */
test('a match over several legs alternates who throws first', () => {
  const g = game({ startScore: 40, players: ['A', 'B'], legsToWin: 2 });
  let state = throwMany(g, [D20]); // A wins leg 1
  assert.equal(state.players[0].legsWon, 1);
  assert.equal(state.matchOver, false);
  assert.equal(state.legNumber, 2);
  assert.equal(state.currentPlayerIndex, 1, 'B throws first in leg 2');
  assert.equal(state.players[0].score, 40, 'scores reset for the new leg');

  state = throwMany(g, [D20]); // B wins leg 2
  assert.equal(state.players[1].legsWon, 1);
  assert.equal(state.currentPlayerIndex, 0, 'A throws first in leg 3');

  state = throwMany(g, [D20]); // A wins leg 3 and the match
  assert.equal(state.matchOver, true);
  assert.equal(state.players[0].legsWon, 2);
});

/* --------------------------------------------------------------- count-up */
test('count-up simply adds and never busts', () => {
  const g = game({ mode: Darts.MODE_COUNT_UP, players: ['A'] });
  const state = throwMany(g, [T20, T20, T20, S20]);
  assert.equal(state.players[0].score, 200);
  assert.equal(state.lastEvent, 'score');
});

/* ------------------------------------------------------------ undo & edit */
test('undo removes the last dart and the score follows', () => {
  const g = game({ players: ['A'] });
  throwMany(g, [T20, T20]);
  const state = g.undo();
  assert.equal(state.players[0].score, 441);
  assert.equal(state.currentTurn.length, 1);
});

test('undo reverses a bust, including the restored score', () => {
  const g = game({ startScore: 50, players: ['A'] });
  throwMany(g, [S20, T20]);
  assert.equal(g.state().players[0].score, 50);
  const state = g.undo();
  assert.equal(state.players[0].score, 30, 'back to mid-turn, not the bust value');
  assert.equal(state.lastEvent, 'score');
  assert.equal(state.currentTurn.length, 1);
});

test('undo can walk all the way back past a completed leg', () => {
  const g = game({ startScore: 40, players: ['A'], legsToWin: 2 });
  throwMany(g, [D20]);
  assert.equal(g.state().players[0].legsWon, 1);
  const state = g.undo();
  assert.equal(state.players[0].legsWon, 0);
  assert.equal(state.players[0].score, 40);
  assert.equal(state.legNumber, 1);
});

test('editing a misrecorded dart recomputes everything after it', () => {
  const g = game({ players: ['A'] });
  throwMany(g, [T20, S1, S20]);
  assert.equal(g.state().players[0].score, 501 - 81);
  // The middle dart was really a treble 1, not a single.
  const state = g.editDart(1, Darts.dart(1, 3));
  assert.equal(state.players[0].score, 501 - 60 - 3 - 20);
});

test('undo on an empty game is harmless', () => {
  const g = game({ players: ['A'] });
  const state = g.undo();
  assert.equal(state.players[0].score, 501);
});

/* --------------------------------------------------------------- checkout */
test('classic checkouts come back as the conventional route', () => {
  assert.deepEqual(Darts.checkout(170).map(Darts.label), ['T20', 'T20', 'Bull']);
  assert.deepEqual(Darts.checkout(40).map(Darts.label), ['D20']);
  assert.deepEqual(Darts.checkout(32).map(Darts.label), ['D16']);
  assert.deepEqual(Darts.checkout(50).map(Darts.label), ['Bull']);
});

test('every checkout returned actually finishes on a double', () => {
  for (let remaining = 2; remaining <= 170; remaining += 1) {
    const route = Darts.checkout(remaining);
    if (!route) continue;
    const total = route.reduce((sum, d) => sum + Darts.points(d), 0);
    assert.equal(total, remaining, `route for ${remaining} totals ${total}`);
    assert.ok(Darts.isDouble(route[route.length - 1]), `route for ${remaining} must end on a double`);
    assert.ok(route.length <= 3);
  }
});

test('scores that cannot be checked out return nothing', () => {
  assert.equal(Darts.checkout(169), null);
  assert.equal(Darts.checkout(168), null);
  assert.equal(Darts.checkout(1), null);
  assert.equal(Darts.checkout(171), null);
});

test('checkout respects how many darts are left in the turn', () => {
  assert.equal(Darts.checkout(170, 2), null, '170 needs three darts');
  assert.deepEqual(Darts.checkout(100, 2).map(Darts.label), ['T20', 'D20']);
  assert.equal(Darts.checkout(100, 1), null);
});

/* ------------------------------------------------------------ persistence */
test('a game survives a round trip through JSON', () => {
  const g = game({ startScore: 301, players: ['A', 'B'], legsToWin: 3 });
  throwMany(g, [T20, S20, D16]);
  const restored = Darts.fromJSON(JSON.parse(JSON.stringify(g.toJSON())));
  assert.deepEqual(restored.state().players[0].score, g.state().players[0].score);
  assert.equal(restored.config.legsToWin, 3);
  assert.equal(restored.state().currentPlayerIndex, g.state().currentPlayerIndex);
});

test('throwing after the match is over changes nothing', () => {
  const g = game({ startScore: 40, players: ['A'] });
  throwMany(g, [D20]);
  const before = g.state().players[0].score;
  const state = g.throwDart(T20);
  assert.equal(state.players[0].score, before);
});
