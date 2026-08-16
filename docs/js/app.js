/* App controller: keypad in, scoreboard out.
 *
 * The engine owns the rules and the stats module owns the numbers; this file
 * only turns taps into darts and state into DOM. Everything is saved to
 * localStorage after every dart, because a game interrupted by a phone call
 * should still be there afterwards.
 */
(function () {
  'use strict';

  var $ = function (id) { return document.getElementById(id); };
  var SAVE_KEY = 'darts.game.v2';

  var app = {
    game: null,
    multiplier: 1,
    editing: null,   // index-from-end of the dart being corrected, or null
    pending: '',
    pendingTimer: null
  };

  /* ------------------------------------------------------------------ *
   * Persistence
   * ------------------------------------------------------------------ */
  function save() {
    try {
      localStorage.setItem(SAVE_KEY, JSON.stringify(app.game.toJSON()));
    } catch (err) { /* private browsing, quota — play on regardless */ }
  }

  function load() {
    try {
      var raw = localStorage.getItem(SAVE_KEY);
      return raw ? Darts.fromJSON(JSON.parse(raw)) : null;
    } catch (err) {
      return null;
    }
  }

  /* ------------------------------------------------------------------ *
   * Rendering
   * ------------------------------------------------------------------ */
  function show(view) {
    ['play', 'stats', 'setup'].forEach(function (name) {
      $('view-' + name).classList.toggle('is-active', name === view);
    });
    if (view === 'stats') renderStats();
    window.scrollTo(0, 0);
  }

  function render() {
    var state = app.game.state();
    renderScores(state);
    renderTurn(state);
    renderCheckout(state);
    renderFlash(state);
    save();
  }

  function renderScores(state) {
    var host = $('scores');
    host.className = 'scores ' + (state.players.length === 2 ? 'two' : state.players.length > 2 ? 'many' : '');
    host.innerHTML = '';
    state.players.forEach(function (player, index) {
      var card = document.createElement('div');
      card.className = 'player' + (index === state.currentPlayerIndex && !state.matchOver ? ' is-live' : '');

      var name = document.createElement('div');
      name.className = 'name';
      var who = document.createElement('span');
      who.textContent = player.name;
      var legs = document.createElement('span');
      legs.textContent = state.config.legsToWin > 1
        ? player.legsWon + '/' + state.config.legsToWin + ' legs' : '';
      name.appendChild(who);
      name.appendChild(legs);
      card.appendChild(name);

      var score = document.createElement('div');
      score.className = 'score';
      score.textContent = player.score;
      card.appendChild(score);

      var meta = document.createElement('div');
      meta.className = 'legs';
      var avg = player.dartsThrown ? (player.pointsScored / player.dartsThrown * 3) : 0;
      meta.textContent = player.dartsThrown
        ? 'avg ' + avg.toFixed(1) + ' · ' + player.dartsThrown + ' darts'
        : 'no darts yet';
      card.appendChild(meta);

      host.appendChild(card);
    });
  }

  function renderTurn(state) {
    var host = $('turn-darts');
    host.innerHTML = '';
    var turn = state.currentTurn;
    for (var i = 0; i < Darts.DARTS_PER_TURN; i++) {
      var d = turn[i];
      var slot = document.createElement('div');
      if (d) {
        var indexFromEnd = turn.length - 1 - i;
        slot.className = 'slot filled' + (app.editing === indexFromEnd ? ' editing' : '');
        slot.textContent = Darts.label(d);
        slot.title = 'Tap to correct this dart';
        (function (target) {
          slot.addEventListener('click', function () { beginEdit(target); });
        })(indexFromEnd);
      } else {
        slot.className = 'slot empty';
        slot.textContent = '·';
      }
      host.appendChild(slot);
    }
    $('turn-total').textContent = turn.reduce(function (sum, d) { return sum + Darts.points(d); }, 0);
  }

  function renderCheckout(state) {
    var hint = $('checkout-hint');
    if (state.matchOver || state.config.mode !== Darts.MODE_X01) { hint.textContent = ''; return; }
    var player = state.players[state.currentPlayerIndex];
    var dartsLeft = Darts.DARTS_PER_TURN - state.currentTurn.length;
    var route = Darts.checkout(player.score, dartsLeft);
    hint.textContent = route
      ? 'Checkout: ' + route.map(Darts.label).join(' · ')
      : (player.score <= 170 ? 'No checkout from ' + player.score : '');
  }

  function renderFlash(state) {
    var flash = $('flash');
    flash.className = 'flash' + (state.matchOver ? ' win' : '');
    flash.textContent = app.editing !== null
      ? 'Correcting a dart — tap its real score.'
      : (state.message || '');
  }

  /* ------------------------------------------------------------------ *
   * Input
   * ------------------------------------------------------------------ */
  function setMultiplier(value) {
    app.multiplier = value;
    Array.prototype.forEach.call(document.querySelectorAll('.mult'), function (button) {
      var on = Number(button.dataset.mult) === value;
      button.classList.toggle('is-on', on);
      button.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
  }

  function beginEdit(indexFromEnd) {
    app.editing = indexFromEnd;
    render();
  }

  function submit(d) {
    if (app.editing !== null) {
      app.game.editDart(app.editing, d);
      app.editing = null;
    } else {
      app.game.throwDart(d);
    }
    // A multiplier applies to one dart, then reverts — leaving "treble" on by
    // accident is the easiest way to record a wrong score.
    setMultiplier(1);
    render();
  }

  function buildKeypad() {
    var host = $('numbers');
    host.innerHTML = '';
    // Numeric order, not board order: you are looking up a number you already
    // know, not reading it off the board.
    for (var n = 1; n <= 20; n++) {
      var key = document.createElement('button');
      key.className = 'key';
      key.type = 'button';
      key.textContent = n;
      key.dataset.number = n;
      host.appendChild(key);
    }
    host.addEventListener('click', function (event) {
      var button = event.target.closest('.key');
      if (button) submit(Darts.dart(Number(button.dataset.number), app.multiplier));
    });

    document.querySelector('.specials').addEventListener('click', function (event) {
      var button = event.target.closest('.key');
      if (!button) return;
      var kind = button.dataset.special;
      if (kind === 'miss') submit(Darts.MISS);
      else if (kind === 'bull') submit(Darts.BULL);
      else submit(Darts.OUTER_BULL);
    });

    document.querySelector('.mult-row').addEventListener('click', function (event) {
      var button = event.target.closest('.mult');
      if (!button) return;
      var value = Number(button.dataset.mult);
      setMultiplier(app.multiplier === value ? 1 : value);
    });
  }

  /* ------------------------------------------------------------------ *
   * Stats
   * ------------------------------------------------------------------ */
  function fmt(value, digits) {
    return Number(value).toFixed(digits === undefined ? 1 : digits);
  }

  function tile(key, value, note) {
    var node = document.createElement('div');
    node.className = 'tile';
    ['k', 'v', 'w'].forEach(function (cls, index) {
      var part = document.createElement('div');
      part.className = cls;
      part.textContent = [key, value, note || ''][index];
      node.appendChild(part);
    });
    return node;
  }

  function th(text) {
    var cell = document.createElement('th');
    cell.textContent = text;
    return cell;
  }

  function renderStats() {
    var state = app.game.state();
    var stats = DartsStats.compute(state);
    var isX01 = state.config.mode === Darts.MODE_X01;

    // Headline tiles: the leader's numbers, since that is what gets read first.
    var summary = $('stats-summary');
    summary.innerHTML = '';
    var best = stats.players.slice().sort(function (a, b) {
      return b.threeDartAverage - a.threeDartAverage;
    })[0];
    if (best) {
      summary.appendChild(tile('Best average', fmt(best.threeDartAverage), best.name));
      summary.appendChild(tile('Darts thrown', stats.totalDarts, 'across the match'));
      summary.appendChild(tile('Highest turn', best.bestTurn, best.name));
      if (isX01) {
        summary.appendChild(tile('Checkout', fmt(best.checkoutPercent, 0) + '%',
          best.checkoutsHit + ' of ' + best.checkoutAttempts + ' chances'));
      }
    }

    // The table is the accessible view of everything the charts show.
    var rows = [
      ['3-dart average', function (p) { return fmt(p.threeDartAverage); }],
      ['First 9 average', function (p) { return fmt(p.firstNineAverage); }],
      ['Darts thrown', function (p) { return p.dartsThrown; }],
      ['Points scored', function (p) { return p.pointsScored; }],
      ['Best turn', function (p) { return p.bestTurn; }],
      ['180s', function (p) { return p.bands['180']; }],
      ['140+', function (p) { return p.bands['140+']; }],
      ['100+', function (p) { return p.bands['100+']; }],
      ['60+', function (p) { return p.bands['60+']; }]
    ];
    if (isX01) {
      rows = rows.concat([
        ['Legs won', function (p) { return p.legsWon; }],
        ['Checkouts', function (p) { return p.checkoutsHit + ' / ' + p.checkoutAttempts; }],
        ['Checkout %', function (p) { return fmt(p.checkoutPercent, 0) + '%'; }],
        ['Highest checkout', function (p) { return p.highestCheckout || '—'; }],
        ['Darts at a double', function (p) { return p.doublesHit + ' / ' + p.doubleAttempts; }],
        ['Busts', function (p) { return p.busts; }]
      ]);
    }

    var table = $('stats-table');
    table.innerHTML = '';
    var head = table.createTHead().insertRow();
    head.appendChild(th(''));
    stats.players.forEach(function (p, index) {
      var cell = th('');
      // The swatch ties each column to its line on the chart.
      var swatch = document.createElement('span');
      swatch.className = 'legend-swatch';
      swatch.style.background = DartsCharts.seriesColour(index);
      cell.appendChild(swatch);
      cell.appendChild(document.createTextNode(' ' + p.name));
      head.appendChild(cell);
    });
    var body = table.createTBody();
    rows.forEach(function (row) {
      var tr = body.insertRow();
      tr.insertCell().textContent = row[0];
      stats.players.forEach(function (p) {
        tr.insertCell().textContent = row[1](p);
      });
    });

    // Charts show the most recent leg that has any turns in it.
    var legs = stats.progression;
    var leg = legs[legs.length - 1];
    $('progression-caption').textContent = leg
      ? (isX01 ? 'Score remaining after each turn — leg ' + leg.leg : 'Running total after each turn')
      : 'Nothing played yet.';
    DartsCharts.progression($('chart-progression'), leg);
    DartsCharts.boardHeatmap($('chart-board'), stats.board);
    renderBoardTable(stats.board);
  }

  function renderBoardTable(board) {
    var table = $('board-table');
    table.innerHTML = '';
    var entries = Object.keys(board.cells).map(function (key) {
      var parts = key.split(':');
      return {
        label: Darts.label(Darts.dart(Number(parts[0]), Number(parts[1]))),
        count: board.cells[key]
      };
    }).sort(function (a, b) { return b.count - a.count; }).slice(0, 8);

    if (board.misses) entries.push({ label: 'Miss', count: board.misses });
    if (!entries.length) return;

    var head = table.createTHead().insertRow();
    head.appendChild(th('Most hit'));
    head.appendChild(th('Darts'));
    var body = table.createTBody();
    entries.forEach(function (entry) {
      var tr = body.insertRow();
      tr.insertCell().textContent = entry.label;
      tr.insertCell().textContent = entry.count;
    });
  }

  /* ------------------------------------------------------------------ *
   * Setup
   * ------------------------------------------------------------------ */
  function readSetup() {
    var chosen = document.querySelector('#setup-mode .chip.is-on');
    var countUp = chosen && chosen.dataset.countup;
    return {
      mode: countUp ? Darts.MODE_COUNT_UP : Darts.MODE_X01,
      startScore: Number((chosen && chosen.dataset.start) || 501),
      // Four is the cap: past that the chart would need a fifth categorical
      // hue, and the palette deliberately does not have one.
      players: $('setup-players').value.split('\n')
        .map(function (s) { return s.trim(); })
        .filter(Boolean)
        .slice(0, 4),
      legsToWin: Math.max(1, Number($('setup-legs').value) || 1),
      doubleOut: $('setup-double-out').checked,
      doubleIn: $('setup-double-in').checked
    };
  }

  function startGame(options) {
    app.game = Darts.createGame(options);
    app.editing = null;
    setMultiplier(1);
    render();
    show('play');
  }

  function bind() {
    $('btn-undo').addEventListener('click', function () {
      app.editing = null;
      app.game.undo();
      render();
    });
    $('btn-stats').addEventListener('click', function () { show('stats'); });
    $('btn-close-stats').addEventListener('click', function () { show('play'); });
    $('btn-setup').addEventListener('click', function () {
      $('setup-players').value = app.game.config.players.join('\n');
      $('setup-legs').value = app.game.config.legsToWin;
      show('setup');
    });
    $('btn-close-setup').addEventListener('click', function () { show('play'); });
    $('btn-start').addEventListener('click', function () { startGame(readSetup()); });

    $('setup-mode').addEventListener('click', function (event) {
      var chip = event.target.closest('.chip');
      if (!chip) return;
      Array.prototype.forEach.call(this.children, function (c) { c.classList.remove('is-on'); });
      chip.classList.add('is-on');
    });

    // A keyboard is quicker than tapping when one is to hand.
    document.addEventListener('keydown', function (event) {
      if (!$('view-play').classList.contains('is-active')) return;
      if (event.target.tagName === 'INPUT' || event.target.tagName === 'TEXTAREA') return;

      if (event.key === 'd') setMultiplier(app.multiplier === 2 ? 1 : 2);
      else if (event.key === 't') setMultiplier(app.multiplier === 3 ? 1 : 3);
      else if (event.key === 'b') submit(Darts.BULL);
      else if (event.key === 'm') submit(Darts.MISS);
      else if (event.key === 'Backspace') { event.preventDefault(); app.game.undo(); render(); }
      else if (/^\d$/.test(event.key)) {
        // Two-digit numbers need a beat: "1" then "2" means 12, not 1 then 2.
        var next = (app.pending || '') + event.key;
        if (Number(next) > 20) next = event.key;
        app.pending = next;
        clearTimeout(app.pendingTimer);
        app.pendingTimer = setTimeout(function () {
          var n = Number(app.pending);
          app.pending = '';
          if (n === 0) submit(Darts.MISS);
          else if (n >= 1 && n <= 20) submit(Darts.dart(n, app.multiplier));
        }, 350);
      }
    });
  }

  function init() {
    buildKeypad();
    bind();
    app.game = load() || Darts.createGame({ players: ['Player 1'] });
    setMultiplier(1);
    render();

    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.register('sw.js').catch(function () { /* offline cache is a bonus */ });
    }
  }

  document.addEventListener('DOMContentLoaded', init);
})();
