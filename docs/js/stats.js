/* Match statistics, computed from the turn record the engine produces.
 *
 * A note on honesty, which shapes what is measurable here: tapping "T20" tells
 * us the segment and ring, not where in that segment the dart landed. So there
 * is no dart-position scatter in this app — the board view aggregates hits per
 * region instead, which is exactly as precise as the data actually is.
 *
 * "Double attempts" is likewise a definition, not a measurement: we count darts
 * thrown while a one-dart finish was available, because intent is not
 * recoverable from a score.
 */
(function (root, factory) {
  var api = factory(typeof require === 'function' ? require('./engine.js') : root.Darts);
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.DartsStats = api;
})(typeof self !== 'undefined' ? self : this, function (Darts) {
  'use strict';

  function average(pointsScored, dartsThrown) {
    if (!dartsThrown) return 0;
    return (pointsScored / dartsThrown) * 3;
  }

  function emptyPlayer(name) {
    return {
      name: name,
      legsWon: 0,
      dartsThrown: 0,
      pointsScored: 0,
      threeDartAverage: 0,
      firstNineAverage: 0,
      bestTurn: 0,
      worstTurn: null,
      turnsPlayed: 0,
      bands: { '180': 0, '140+': 0, '100+': 0, '60+': 0 },
      checkoutAttempts: 0,
      checkoutsHit: 0,
      checkoutPercent: 0,
      highestCheckout: 0,
      doubleAttempts: 0,
      doublesHit: 0,
      doublePercent: 0,
      busts: 0
    };
  }

  function bandFor(scored) {
    if (scored === 180) return '180';
    if (scored >= 140) return '140+';
    if (scored >= 100) return '100+';
    if (scored >= 60) return '60+';
    return null;
  }

  /* Walk one turn dart by dart to count chances at a finish. */
  function countDoubleChances(turn, player, isX01) {
    if (!isX01) return;
    var remaining = turn.startScore;
    turn.darts.forEach(function (d) {
      var oneDartFinish = Darts.checkout(remaining, 1);
      if (oneDartFinish) {
        player.doubleAttempts += 1;
        if (Darts.points(d) === remaining && Darts.isDouble(d)) player.doublesHit += 1;
      }
      var next = remaining - Darts.points(d);
      remaining = next < 0 ? turn.startScore : next;
    });
  }

  function compute(state) {
    var isX01 = state.config.mode === Darts.MODE_X01;
    var players = state.players.map(function (p) {
      var stats = emptyPlayer(p.name);
      stats.legsWon = p.legsWon;
      stats.dartsThrown = p.dartsThrown;
      return stats;
    });

    // Turns, in order, across every leg.
    var allTurns = [];
    state.players.forEach(function (p, index) {
      p.turns.forEach(function (turn) {
        allTurns.push({ turn: turn, playerIndex: index });
      });
    });

    // The turn in progress counts too. Its darts have been thrown, so leaving
    // them out understates the average and loses them from the board view —
    // but it is not a *turn* yet, so it stays out of the turn-level bands.
    if (state.currentTurn.length) {
      allTurns.push({
        playerIndex: state.currentPlayerIndex,
        inProgress: true,
        turn: {
          leg: state.legNumber,
          darts: state.currentTurn.slice(),
          scored: state.currentTurn.reduce(function (sum, d) { return sum + Darts.points(d); }, 0),
          busted: false,
          startScore: state.turnStartScore,
          endScore: state.players[state.currentPlayerIndex].score
        }
      });
    }

    allTurns.forEach(function (entry) {
      var turn = entry.turn;
      var player = players[entry.playerIndex];

      player.pointsScored += turn.scored;
      if (entry.inProgress) return;

      player.turnsPlayed += 1;
      if (turn.busted) player.busts += 1;

      if (turn.scored > player.bestTurn) player.bestTurn = turn.scored;
      if (player.worstTurn === null || turn.scored < player.worstTurn) player.worstTurn = turn.scored;

      var band = bandFor(turn.scored);
      if (band) player.bands[band] += 1;

      if (isX01) {
        // A turn beginning on a checkable score is a chance at the leg.
        if (turn.startScore <= 170 && Darts.checkout(turn.startScore)) {
          player.checkoutAttempts += 1;
          if (turn.endScore === 0) {
            player.checkoutsHit += 1;
            if (turn.startScore > player.highestCheckout) player.highestCheckout = turn.startScore;
          }
        }
        countDoubleChances(turn, player, isX01);
      }
    });

    // First-nine average is measured per leg, since each leg restarts.
    var firstNine = players.map(function () { return { points: 0, darts: 0 }; });
    var perLegDarts = {};
    allTurns.forEach(function (entry) {
      var key = entry.playerIndex + ':' + entry.turn.leg;
      var used = perLegDarts[key] || 0;
      if (used < 9) {
        var room = 9 - used;
        // A turn is three darts; count the whole turn if it fits in the first nine.
        if (entry.turn.darts.length <= room) {
          firstNine[entry.playerIndex].points += entry.turn.scored;
          firstNine[entry.playerIndex].darts += entry.turn.darts.length;
        }
      }
      perLegDarts[key] = used + entry.turn.darts.length;
    });

    players.forEach(function (player, index) {
      player.threeDartAverage = average(player.pointsScored, player.dartsThrown);
      player.firstNineAverage = average(firstNine[index].points, firstNine[index].darts);
      player.checkoutPercent = player.checkoutAttempts
        ? (player.checkoutsHit / player.checkoutAttempts) * 100 : 0;
      player.doublePercent = player.doubleAttempts
        ? (player.doublesHit / player.doubleAttempts) * 100 : 0;
      if (player.worstTurn === null) player.worstTurn = 0;
    });

    return {
      players: players,
      progression: progression(state),
      board: boardCounts(state),
      totalDarts: players.reduce(function (sum, p) { return sum + p.dartsThrown; }, 0)
    };
  }

  /* Score remaining after each turn, per player, per leg — the shape of the leg. */
  function progression(state) {
    var isX01 = state.config.mode === Darts.MODE_X01;
    var legs = {};
    state.players.forEach(function (p, playerIndex) {
      p.turns.forEach(function (turn) {
        var leg = legs[turn.leg] || (legs[turn.leg] = { leg: turn.leg, series: [] });
        var series = leg.series[playerIndex] || (leg.series[playerIndex] = {
          player: p.name,
          playerIndex: playerIndex,
          points: [{ turn: 0, value: isX01 ? turn.startScore : 0 }]
        });
        series.points.push({ turn: series.points.length, value: turn.endScore });
      });
    });
    return Object.keys(legs)
      .map(function (key) { return legs[key]; })
      .sort(function (a, b) { return a.leg - b.leg; })
      .map(function (leg) {
        leg.series = leg.series.filter(Boolean);
        return leg;
      });
  }

  /* How often each region of the board was hit — the honest heatmap input. */
  function boardCounts(state) {
    var cells = {};
    var max = 0;
    var total = 0;
    var misses = 0;

    function record(d) {
      total += 1;
      if (!d.multiplier || !d.segment) { misses += 1; return; }
      var key = d.segment + ':' + d.multiplier;
      cells[key] = (cells[key] || 0) + 1;
      if (cells[key] > max) max = cells[key];
    }

    state.players.forEach(function (p) {
      p.turns.forEach(function (turn) { turn.darts.forEach(record); });
    });
    // Darts thrown in the turn currently under way count as well.
    state.currentTurn.forEach(record);

    return { cells: cells, max: max, total: total, misses: misses };
  }

  return {
    compute: compute,
    progression: progression,
    boardCounts: boardCounts,
    average: average
  };
});
