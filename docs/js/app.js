/* App controller: wires camera -> server -> scoreboard, plus the manual
 * corrections that make the whole thing usable when detection gets it wrong. */
(function () {
  'use strict';

  var $ = function (id) { return document.getElementById(id); };

  var state = {
    settings: Api.loadSettings(),
    game: null,
    calibrated: false,
    connected: false,
    busy: false,
    cooldownUntil: 0,
    lastFrameDataUrl: null,
    manualTarget: null, // dart id when editing, null when adding
    manualSegment: 20
  };

  var camera = new Camera($('video'), $('capture-canvas'), $('motion-canvas'));
  var calibrator = new Calibrator($('calib-canvas'), { onChange: renderCalibrationProgress });

  /* ------------------------------------------------------------------ *
   * Banners
   * ------------------------------------------------------------------ */
  function showBanner(message, kind, key) {
    var area = $('banner-area');
    var id = 'banner-' + (key || Math.random().toString(36).slice(2));
    var existing = document.getElementById(id);
    if (existing) existing.remove();
    var node = document.createElement('div');
    node.id = id;
    node.className = 'banner banner-' + (kind || 'info');
    node.textContent = message;
    area.appendChild(node);
    if (kind !== 'error') {
      setTimeout(function () { if (node.parentNode) node.remove(); }, 8000);
    }
  }

  function clearBanners() { $('banner-area').innerHTML = ''; }

  /* ------------------------------------------------------------------ *
   * Rendering
   * ------------------------------------------------------------------ */
  function setConnection(status) {
    state.connected = status === 'ok';
    var dot = $('conn-dot');
    dot.className = 'dot ' + (status === 'ok' ? 'dot-green' : status === 'warn' ? 'dot-amber' : 'dot-red');
    dot.title = status === 'ok' ? 'Connected' : 'Disconnected';
  }

  function renderGame(game) {
    if (!game) return;
    state.game = game;
    $('player-name').textContent = game.current_player;
    $('total-score').textContent = game.players[game.current_player_index].score;
    $('mode-label').textContent =
      (game.mode === 'x01' ? game.start_score + ' / x01' : 'Count-up') + ' · turn ' + game.turn_number;
    $('turn-total').textContent = game.turn_total;

    var slots = $('turn-darts');
    slots.innerHTML = '';
    for (var i = 0; i < 3; i++) {
      var dart = game.current_turn[i];
      var slot = document.createElement('div');
      if (dart) {
        slot.className = 'dart-slot' + (dart.low_confidence ? ' low-confidence' : '') + (dart.source === 'manual' ? ' manual' : '');
        slot.innerHTML = dart.label + '<small>' + dart.points + ' pts · tap to fix</small>';
        slot.dataset.dartId = dart.id;
        slot.addEventListener('click', onEditDart);
      } else {
        slot.className = 'dart-slot empty';
        slot.textContent = String(i + 1);
      }
      slots.appendChild(slot);
    }

    BoardView.render($('board-diagram'), game.current_turn);

    var history = $('history');
    history.innerHTML = '';
    game.players.forEach(function (player) {
      player.turns.slice(-8).forEach(function (turn, index) {
        var total = turn.reduce(function (sum, d) { return sum + d.points; }, 0);
        var item = document.createElement('li');
        item.innerHTML = '<span>' + player.name + ' · ' +
          (turn.map(function (d) { return d.label; }).join(', ') || '—') + '</span><strong>' + total + '</strong>';
        history.appendChild(item);
        void index;
      });
    });

    if (game.winner) showBanner(game.winner + ' wins!', 'info', 'winner');
    if (game.bust) showBanner('Bust — turn over, score reverted.', 'warn', 'bust');
    (game.warnings || []).forEach(function (w) { showBanner(w, 'warn'); });
  }

  function renderCalibrationProgress() {
    var list = $('ref-list');
    var points = calibrator.referencePoints || [];
    list.innerHTML = '';
    points.forEach(function (point, index) {
      var item = document.createElement('li');
      item.textContent = point.name;
      if (index < calibrator.points.length) item.className = 'done';
      else if (index === calibrator.points.length) item.className = 'next';
      list.appendChild(item);
    });
    $('btn-send-calibration').disabled = !calibrator.isComplete();
  }

  /* ------------------------------------------------------------------ *
   * Server sync
   * ------------------------------------------------------------------ */
  function refreshStatus() {
    return Api.status().then(function (status) {
      setConnection(status.needs_recalibration ? 'warn' : 'ok');
      state.calibrated = status.calibrated;
      renderGame(status.game);
      $('status-dump').textContent = JSON.stringify(status, null, 2);
      $('server-status').textContent = 'Connected to ' + Api.baseUrl +
        ' · calibrated: ' + status.calibrated + ' · Ollama: ' + (status.ollama.available ? status.ollama.model : 'offline');
      $('calib-status').textContent = status.calibrated
        ? 'Calibrated (fit error ' + status.calibration_rms_error_mm + ' mm).'
        : 'Not calibrated — the server cannot score until this is done.';
      if (status.needs_recalibration) {
        showBanner('The camera looks like it moved. Recalibrate before trusting scores.', 'warn', 'recal');
      }
      return status;
    }).catch(function (err) {
      setConnection('down');
      $('server-status').textContent = err.message;
      throw err;
    });
  }

  /* ------------------------------------------------------------------ *
   * Capture loop
   * ------------------------------------------------------------------ */
  function captureAndScore(options) {
    options = options || {};
    if (state.busy) return Promise.resolve();
    var dataUrl = camera.capture();
    if (!dataUrl) return Promise.resolve();
    state.lastFrameDataUrl = dataUrl;
    state.busy = true;
    $('detect-status').textContent = options.setReference ? 'capturing reference…' : 'scoring…';

    return Api.frame({ image: dataUrl, set_reference: !!options.setReference })
      .then(function (result) {
        setConnection(result.needs_recalibration ? 'warn' : 'ok');
        if (result.status === 'reference_captured') {
          $('detect-status').textContent = 'reference captured';
          showBanner('Clear-board reference captured — throw away.', 'info', 'ref');
        } else if (result.status === 'scene_changed') {
          $('detect-status').textContent = 'scene changed';
        } else {
          $('detect-status').textContent = result.new_darts.length
            ? 'scored ' + result.new_darts.map(function (d) { return d.label; }).join(', ')
            : 'no new darts';
        }
        (result.warnings || []).forEach(function (w) { showBanner(w, 'warn'); });
        renderGame(result.game);
        if (result.new_darts && result.new_darts.length) {
          // Cooldown stops the same dart re-triggering while the board settles.
          state.cooldownUntil = Date.now() + Number(state.settings.cooldownMs || 0);
        }
        return result;
      })
      .catch(function (err) {
        if (err.status === 409) {
          showBanner('Server is not calibrated yet — open the Calibrate tab.', 'error', 'nocal');
        } else {
          setConnection('down');
          showBanner(err.message, 'error', 'frame-error');
        }
      })
      .finally(function () {
        camera.resetMotion();
        state.busy = false;
      });
  }

  function motionTick() {
    if (!camera.isRunning()) return;
    var level = camera.motionLevel();
    $('motion-readout').textContent = 'motion ' + (level * 100).toFixed(1) + '%';
    if (!$('auto-capture').checked) return;
    if (Date.now() < state.cooldownUntil) return;
    if (state.busy) return;
    if (level * 100 >= Number(state.settings.motionThreshold || 2)) {
      // Wait a beat so the frame we send is of a settled dart, not a blur.
      state.busy = true;
      setTimeout(function () { state.busy = false; captureAndScore(); }, 350);
    }
  }

  /* ------------------------------------------------------------------ *
   * Manual entry
   * ------------------------------------------------------------------ */
  function buildSegmentGrid() {
    var grid = $('segment-grid');
    grid.innerHTML = '';
    BoardView.order.slice().sort(function (a, b) { return a - b; }).concat([25, 0]).forEach(function (segment) {
      var button = document.createElement('button');
      button.type = 'button';
      button.textContent = segment === 25 ? 'BULL' : segment === 0 ? 'MISS' : segment;
      button.dataset.segment = segment;
      if (segment === state.manualSegment) button.classList.add('selected');
      button.addEventListener('click', function () {
        state.manualSegment = segment;
        Array.prototype.forEach.call(grid.children, function (child) { child.classList.remove('selected'); });
        button.classList.add('selected');
      });
      grid.appendChild(button);
    });
  }

  function ringValue() {
    var checked = document.querySelector('input[name="ring"]:checked');
    return checked ? checked.value : 'inner_single';
  }

  function openManualDialog(dartId) {
    state.manualTarget = dartId || null;
    $('manual-title').textContent = dartId ? 'Correct dart' : 'Add dart';
    buildSegmentGrid();
    $('manual-dialog').showModal();
  }

  function onEditDart(event) {
    openManualDialog(event.currentTarget.dataset.dartId);
  }

  function submitManual() {
    var segment = state.manualSegment;
    var ring = segment === 25 ? 'inner_bull' : segment === 0 ? 'miss' : ringValue();
    var payload = { segment: segment, ring: ring };
    if (segment === 0) { payload = { x_mm: 0, y_mm: 250 }; } // guaranteed off-board => MISS
    var call = state.manualTarget
      ? Api.editDart(Object.assign({ dart_id: state.manualTarget }, payload))
      : Api.addDart(payload);
    call.then(function (result) {
      renderGame(result.game);
    }).catch(function (err) {
      showBanner(err.message, 'error');
    });
  }

  /* ------------------------------------------------------------------ *
   * Wiring
   * ------------------------------------------------------------------ */
  function bindTabs() {
    Array.prototype.forEach.call(document.querySelectorAll('.tab'), function (tab) {
      tab.addEventListener('click', function () {
        Array.prototype.forEach.call(document.querySelectorAll('.tab'), function (t) { t.classList.remove('is-active'); });
        Array.prototype.forEach.call(document.querySelectorAll('.view'), function (v) { v.classList.remove('is-active'); });
        tab.classList.add('is-active');
        $('view-' + tab.dataset.view).classList.add('is-active');
      });
    });
  }

  function loadSettingsIntoForm() {
    var settings = state.settings;
    $('server-url').value = Api.baseUrl;
    $('game-mode').value = settings.mode;
    $('start-score').value = settings.startScore;
    $('players').value = settings.players.join('\n');
    $('motion-threshold').value = settings.motionThreshold;
    $('cooldown-ms').value = settings.cooldownMs;
  }

  function saveSettingsFromForm() {
    state.settings = Api.saveSettings({
      mode: $('game-mode').value,
      startScore: Number($('start-score').value) || 501,
      players: $('players').value.split('\n').map(function (s) { return s.trim(); }).filter(Boolean),
      motionThreshold: Number($('motion-threshold').value) || 2,
      cooldownMs: Number($('cooldown-ms').value) || 0
    });
    showBanner('Settings saved.', 'info', 'settings');
  }

  function bindControls() {
    $('btn-start-camera').addEventListener('click', function () {
      if (camera.isRunning()) {
        camera.stop();
        $('camera-status').textContent = 'off';
        $('btn-start-camera').textContent = 'Start camera';
        return;
      }
      camera.start().then(function () {
        $('camera-status').textContent = 'live';
        $('btn-start-camera').textContent = 'Stop camera';
        // First frame with a clear board becomes the diff reference.
        return captureAndScore({ setReference: true });
      }).catch(function (err) {
        showBanner(err.message, 'error', 'camera');
        $('camera-status').textContent = 'error';
      });
    });

    $('btn-next-turn').addEventListener('click', function () {
      var image = camera.isRunning() ? camera.capture() : null;
      Api.nextTurn(image ? { image: image } : {})
        .then(function (result) {
          renderGame(result.game);
          camera.resetMotion();
          showBanner('Next turn — pull the darts out, the board reference resets.', 'info', 'turn');
        })
        .catch(function (err) { showBanner(err.message, 'error'); });
    });

    $('btn-undo').addEventListener('click', function () {
      Api.undoDart()
        .then(function (result) { renderGame(result.game); })
        .catch(function (err) { showBanner(err.message, 'error'); });
    });

    $('btn-manual').addEventListener('click', function () { openManualDialog(null); });

    $('manual-dialog').addEventListener('close', function () {
      if ($('manual-dialog').returnValue === 'ok') submitManual();
    });

    $('btn-verify').addEventListener('click', function () {
      var image = state.lastFrameDataUrl || (camera.isRunning() ? camera.capture() : null);
      if (!image) { showBanner('Start the camera first.', 'warn'); return; }
      showBanner('Asking the vision model… this takes a few seconds.', 'info', 'verify');
      Api.verify({ image: image }).then(function (result) {
        if (!result.verify.available) {
          showBanner('Verification unavailable: ' + result.verify.error, 'error', 'verify');
          return;
        }
        if (result.warnings.length) {
          result.warnings.forEach(function (w) { showBanner(w, 'warn'); });
        } else {
          showBanner('Vision check agrees: ' + result.verify.dart_count + ' dart(s).', 'info', 'verify');
        }
      }).catch(function (err) { showBanner(err.message, 'error', 'verify'); });
    });

    $('btn-reset').addEventListener('click', function () {
      var image = camera.isRunning() ? camera.capture() : null;
      Api.reset({
        mode: state.settings.mode,
        players: state.settings.players,
        start_score: state.settings.startScore,
        image: image
      }).then(function (result) {
        clearBanners();
        renderGame(result.game);
        camera.resetMotion();
        showBanner('New game started.', 'info', 'newgame');
      }).catch(function (err) { showBanner(err.message, 'error'); });
    });

    $('btn-save-server').addEventListener('click', function () {
      Api.setBaseUrl($('server-url').value);
      $('server-url').value = Api.baseUrl;
      refreshStatus().catch(function () {});
    });
    $('btn-test').addEventListener('click', function () { refreshStatus().catch(function () {}); });
    $('btn-save-settings').addEventListener('click', saveSettingsFromForm);

    $('btn-freeze').addEventListener('click', function () {
      var take = camera.isRunning() ? Promise.resolve() : camera.start().then(function () {
        $('camera-status').textContent = 'live';
        $('btn-start-camera').textContent = 'Stop camera';
      });
      take.then(function () {
        var dataUrl = camera.capture(1280, 0.9);
        if (!dataUrl) throw new Error('Camera has not produced a frame yet.');
        return calibrator.setFrame(dataUrl);
      }).catch(function (err) { showBanner(err.message, 'error', 'freeze'); });
    });

    $('btn-clear-points').addEventListener('click', function () { calibrator.clearPoints(); });

    $('btn-send-calibration').addEventListener('click', function () {
      Api.calibrate(calibrator.payload()).then(function (result) {
        state.calibrated = true;
        calibrator.setOverlay(result.board_outline_px);
        $('calib-status').textContent = 'Saved. Fit error ' + result.rms_error_mm +
          ' mm — the green outline should sit on the outer wire.';
        showBanner('Calibration saved.', 'info', 'cal');
        return refreshStatus();
      }).catch(function (err) { showBanner(err.message, 'error', 'cal'); });
    });

    $('btn-show-overlay').addEventListener('click', function () {
      Api.getCalibration().then(function (result) {
        if (!result.calibrated) { showBanner('No calibration stored yet.', 'warn'); return; }
        calibrator.setOverlay(result.board_outline_px);
      }).catch(function (err) { showBanner(err.message, 'error'); });
    });
  }

  function registerServiceWorker() {
    if (!('serviceWorker' in navigator)) return;
    // Resolved relative to this script so it works under a GitHub Pages subpath.
    navigator.serviceWorker.register('sw.js').catch(function () { /* offline shell is optional */ });
  }

  function init() {
    bindTabs();
    bindControls();
    loadSettingsIntoForm();
    registerServiceWorker();

    // Default to the origin we were served from, which is right when the page
    // is opened straight off the desktop server.
    if (!Api.baseUrl && location.protocol.startsWith('http') && !/github\.io$/.test(location.hostname)) {
      Api.setBaseUrl(location.origin);
      $('server-url').value = Api.baseUrl;
    }

    calibrator.setReferencePoints([]);
    Api.getCalibration().then(function (result) {
      calibrator.setReferencePoints(result.reference_points || []);
      renderCalibrationProgress();
      if (result.calibrated && result.board_outline_px) calibrator.setOverlay(result.board_outline_px);
    }).catch(function () { renderCalibrationProgress(); });

    refreshStatus().catch(function () {
      showBanner('Cannot reach the server. Check the address in Settings and that start.bat is running.', 'error', 'conn');
    });

    setInterval(function () { refreshStatus().catch(function () {}); }, 10000);
    setInterval(motionTick, 250);
  }

  document.addEventListener('DOMContentLoaded', init);
})();
