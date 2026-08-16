/* Darts game engine — the rules, and nothing else.
 *
 * Runs in the browser and under Node (so it can be tested directly). It holds
 * no DOM and no storage; the app layer owns those.
 *
 * The design decision that matters: a game is stored as the flat list of darts
 * thrown, and every piece of state — whose turn it is, each score, legs won,
 * whether that last dart was a bust — is *derived* by replaying that list.
 * Undo is then a pop, editing a misrecorded dart is a splice, and neither can
 * leave the score out of step with the history, which is exactly the class of
 * bug that unwinding deltas by hand tends to produce.
 */
(function (root, factory) {
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.Darts = api;
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  var DARTS_PER_TURN = 3;
  var SEGMENTS = [20, 1, 18, 4, 13, 6, 10, 15, 2, 17, 3, 19, 7, 16, 8, 11, 14, 9, 12, 5];

  var MODE_X01 = 'x01';
  var MODE_COUNT_UP = 'countup';

  /* ------------------------------------------------------------------ *
   * Darts
   * ------------------------------------------------------------------ */
  function dart(segment, multiplier) {
    return { segment: segment, multiplier: multiplier };
  }

  var MISS = dart(0, 0);
  var OUTER_BULL = dart(25, 1);
  var BULL = dart(25, 2);

  function points(d) {
    if (!d || !d.multiplier) return 0;
    return d.segment * d.multiplier;
  }

  /* A bull counts as a double for checkout purposes — it is the 50 ring. */
  function isDouble(d) {
    return !!d && d.multiplier === 2;
  }

  function label(d) {
    if (!d || d.multiplier === 0 || d.segment === 0) return 'Miss';
    if (d.segment === 25) return d.multiplier === 2 ? 'Bull' : '25';
    return (d.multiplier === 2 ? 'D' : d.multiplier === 3 ? 'T' : '') + d.segment;
  }

  function parseLabel(text) {
    var raw = String(text).trim().toUpperCase();
    if (raw === 'MISS' || raw === '0') return dart(0, 0);
    if (raw === 'BULL' || raw === 'DB' || raw === '50') return dart(25, 2);
    if (raw === '25' || raw === 'SB') return dart(25, 1);
    var match = /^([SDT]?)(\d{1,2})$/.exec(raw);
    if (!match) return null;
    var segment = Number(match[2]);
    if (SEGMENTS.indexOf(segment) === -1) return null;
    var multiplier = match[1] === 'D' ? 2 : match[1] === 'T' ? 3 : 1;
    return dart(segment, multiplier);
  }

  /* Every throw available on a board, used by the checkout finder. */
  function allThrows() {
    var list = [BULL, OUTER_BULL];
    SEGMENTS.forEach(function (segment) {
      list.push(dart(segment, 3));
      list.push(dart(segment, 2));
      list.push(dart(segment, 1));
    });
    return list;
  }

  var ALL_THROWS = allThrows();
  var DOUBLES = ALL_THROWS.filter(isDouble);

  /* ------------------------------------------------------------------ *
   * Checkout finder
   * ------------------------------------------------------------------ */
  /* Players expect the conventional route, not merely a valid one: 170 should
   * come back as T20 T20 Bull, and a finish should leave a friendly double.
   * These weights encode that preference rather than a hardcoded table, so odd
   * scores and double-in variants still get an answer. */
  function throwPreference(d) {
    if (d.segment === 20 && d.multiplier === 3) return 0;
    if (d.segment === 19 && d.multiplier === 3) return 1;
    if (d.multiplier === 3) return 3;
    if (d.segment === 25) return 2;
    if (d.multiplier === 1 && [20, 19, 18, 17, 16].indexOf(d.segment) !== -1) return 2;
    return 4;
  }

  function doublePreference(d) {
    // Doubles players actually want to be left on, best first.
    var order = [16, 20, 8, 10, 4, 12, 18, 2, 6, 14, 25, 5, 9, 11, 13, 15, 17, 19, 1, 3, 7];
    var index = order.indexOf(d.segment);
    return index === -1 ? order.length : index;
  }

  function checkout(remaining, dartsLeft) {
    dartsLeft = dartsLeft === undefined ? DARTS_PER_TURN : dartsLeft;
    if (remaining < 2 || remaining > 170 || dartsLeft < 1) return null;

    var best = null;
    function consider(route) {
      // Fewest darts dominates; then what you throw *first* (a 141 is opened
      // with T20, not a bull); the double you are left on is only a tiebreak.
      // Weighting these equally makes routes tie, and the winner then depends
      // on enumeration order rather than on how anyone actually plays.
      var cost = route.length * 1000 + doublePreference(route[route.length - 1]);
      route.forEach(function (d, index) {
        if (index < route.length - 1) cost += throwPreference(d) * 10;
      });
      if (!best || cost < best.cost) best = { route: route, cost: cost };
    }

    // One dart.
    DOUBLES.forEach(function (d) {
      if (points(d) === remaining) consider([d]);
    });
    // Two darts.
    if (!best && dartsLeft >= 2) {
      ALL_THROWS.forEach(function (first) {
        var rest = remaining - points(first);
        DOUBLES.forEach(function (d) {
          if (points(d) === rest) consider([first, d]);
        });
      });
    }
    // Three darts.
    if (!best && dartsLeft >= 3) {
      ALL_THROWS.forEach(function (first) {
        var afterFirst = remaining - points(first);
        if (afterFirst < 2) return;
        ALL_THROWS.forEach(function (second) {
          var rest = afterFirst - points(second);
          if (rest < 2) return;
          DOUBLES.forEach(function (d) {
            if (points(d) === rest) consider([first, second, d]);
          });
        });
      });
    }
    return best ? best.route : null;
  }

  /* ------------------------------------------------------------------ *
   * Replay — derives all state from the list of darts
   * ------------------------------------------------------------------ */
  function defaultConfig(overrides) {
    var config = {
      mode: MODE_X01,
      startScore: 501,
      players: ['Player 1'],
      doubleOut: true,
      doubleIn: false,
      legsToWin: 1
    };
    Object.keys(overrides || {}).forEach(function (key) {
      if (overrides[key] !== undefined) config[key] = overrides[key];
    });
    if (!config.players.length) config.players = ['Player 1'];
    return config;
  }

  function newPlayer(name, startScore) {
    return {
      name: name,
      score: startScore,
      legsWon: 0,
      dartsThrown: 0,
      pointsScored: 0,
      turns: [],
      openedIn: false
    };
  }

  function replay(config, darts) {
    var startScore = config.mode === MODE_X01 ? config.startScore : 0;
    var players = config.players.map(function (name) { return newPlayer(name, startScore); });

    var state = {
      config: config,
      players: players,
      currentPlayerIndex: 0,
      currentTurn: [],
      turnStartScore: startScore,
      legNumber: 1,
      legStartPlayerIndex: 0,
      legs: [],          // completed legs: {winner, turns:[...]}
      legTurns: [],      // turns played in the current leg
      matchOver: false,
      winner: null,
      lastEvent: null,   // 'bust' | 'leg' | 'match' | 'score'
      message: ''
    };

    darts.forEach(function (d) { applyDart(state, d); });
    return state;
  }

  function currentPlayer(state) {
    return state.players[state.currentPlayerIndex];
  }

  function finishTurn(state, reason) {
    var player = currentPlayer(state);
    var record = {
      player: player.name,
      playerIndex: state.currentPlayerIndex,
      leg: state.legNumber,
      darts: state.currentTurn.slice(),
      scored: state.currentTurn.reduce(function (sum, d) { return sum + points(d); }, 0),
      busted: reason === 'bust',
      startScore: state.turnStartScore,
      endScore: player.score
    };
    if (record.busted) record.scored = 0;
    player.turns.push(record);
    state.legTurns.push(record);

    state.currentTurn = [];
    state.currentPlayerIndex = (state.currentPlayerIndex + 1) % state.players.length;
    state.turnStartScore = currentPlayer(state).score;
  }

  function startNextLeg(state) {
    state.legs.push({
      number: state.legNumber,
      winner: state.winner,
      turns: state.legTurns.slice()
    });
    state.legTurns = [];
    state.legNumber += 1;
    // The player who threw first last leg does not throw first again.
    state.legStartPlayerIndex = (state.legStartPlayerIndex + 1) % state.players.length;
    state.currentPlayerIndex = state.legStartPlayerIndex;
    state.currentTurn = [];
    state.players.forEach(function (player) {
      player.score = state.config.mode === MODE_X01 ? state.config.startScore : 0;
      player.openedIn = false;
    });
    state.turnStartScore = currentPlayer(state).score;
    state.winner = null;
  }

  function applyDart(state, d) {
    if (state.matchOver) return state;
    var player = currentPlayer(state);

    if (state.currentTurn.length === 0) state.turnStartScore = player.score;
    state.currentTurn.push(d);
    player.dartsThrown += 1;
    state.message = '';

    if (state.config.mode === MODE_COUNT_UP) {
      player.score += points(d);
      player.pointsScored += points(d);
      state.lastEvent = 'score';
      if (state.currentTurn.length >= DARTS_PER_TURN) finishTurn(state, 'complete');
      return state;
    }

    // --- x01 ---------------------------------------------------------
    if (state.config.doubleIn && !player.openedIn) {
      if (!isDouble(d)) {
        // Nothing counts until a double is hit.
        state.lastEvent = 'score';
        if (state.currentTurn.length >= DARTS_PER_TURN) finishTurn(state, 'complete');
        return state;
      }
      player.openedIn = true;
    }

    var remaining = player.score - points(d);
    var bust =
      remaining < 0 ||
      remaining === 1 && state.config.doubleOut ||
      remaining === 0 && state.config.doubleOut && !isDouble(d);

    if (bust) {
      player.score = state.turnStartScore;
      state.lastEvent = 'bust';
      state.message = player.name + ' bust on ' + label(d);
      finishTurn(state, 'bust');
      return state;
    }

    player.score = remaining;
    player.pointsScored += points(d);

    if (remaining === 0) {
      player.legsWon += 1;
      state.winner = player.name;
      finishTurn(state, 'leg');
      // finishTurn advanced the player; the leg record needs the winner name.
      if (player.legsWon >= state.config.legsToWin) {
        state.matchOver = true;
        state.lastEvent = 'match';
        state.message = player.name + ' wins the match';
        state.legs.push({ number: state.legNumber, winner: player.name, turns: state.legTurns.slice() });
        state.legTurns = [];
      } else {
        state.lastEvent = 'leg';
        state.message = player.name + ' takes leg ' + state.legNumber;
        startNextLeg(state);
      }
      return state;
    }

    state.lastEvent = 'score';
    if (state.currentTurn.length >= DARTS_PER_TURN) finishTurn(state, 'complete');
    return state;
  }

  /* ------------------------------------------------------------------ *
   * Game facade
   * ------------------------------------------------------------------ */
  function createGame(options) {
    var config = defaultConfig(options);
    var darts = (options && options.darts ? options.darts.slice() : []);

    var game = {
      config: config,
      darts: darts,

      state: function () { return replay(config, darts); },

      throwDart: function (d) {
        var state = this.state();
        if (state.matchOver) return state;
        darts.push(d);
        return this.state();
      },

      undo: function () {
        darts.pop();
        return this.state();
      },

      /* Correct a dart already thrown, counted back from the most recent. */
      editDart: function (indexFromEnd, replacement) {
        var index = darts.length - 1 - indexFromEnd;
        if (index < 0 || index >= darts.length) return this.state();
        darts[index] = replacement;
        return this.state();
      },

      reset: function () {
        darts.length = 0;
        return this.state();
      },

      toJSON: function () {
        return { config: config, darts: darts };
      }
    };
    return game;
  }

  function fromJSON(saved) {
    if (!saved || !saved.config) return null;
    var options = {};
    Object.keys(saved.config).forEach(function (key) { options[key] = saved.config[key]; });
    options.darts = saved.darts || [];
    return createGame(options);
  }

  return {
    DARTS_PER_TURN: DARTS_PER_TURN,
    SEGMENTS: SEGMENTS,
    MODE_X01: MODE_X01,
    MODE_COUNT_UP: MODE_COUNT_UP,
    MISS: MISS,
    BULL: BULL,
    OUTER_BULL: OUTER_BULL,
    dart: dart,
    points: points,
    isDouble: isDouble,
    label: label,
    parseLabel: parseLabel,
    allThrows: function () { return ALL_THROWS.slice(); },
    checkout: checkout,
    replay: replay,
    createGame: createGame,
    fromJSON: fromJSON
  };
});
