/* Talking to the desktop server.
 *
 * The server address is never hardcoded — it lives in localStorage and is
 * edited in Settings, because the desktop's LAN IP differs per house and can
 * change when the router hands out a new lease.
 */
(function (global) {
  'use strict';

  var STORAGE_KEY = 'darts.serverUrl';
  var SETTINGS_KEY = 'darts.settings';

  var DEFAULT_SETTINGS = {
    mode: 'count_up',
    startScore: 501,
    players: ['Player 1'],
    motionThreshold: 0.15, // percent of pixels that must change; a single
                           // landed dart measures ~0.2-0.5%, camera noise ~0.0%
    cooldownMs: 1500
  };

  function normaliseUrl(url) {
    if (!url) return '';
    var trimmed = url.trim().replace(/\/+$/, '');
    if (!/^https?:\/\//i.test(trimmed)) trimmed = 'http://' + trimmed;
    return trimmed;
  }

  var Api = {
    baseUrl: normaliseUrl(localStorage.getItem(STORAGE_KEY) || ''),

    setBaseUrl: function (url) {
      this.baseUrl = normaliseUrl(url);
      localStorage.setItem(STORAGE_KEY, this.baseUrl);
      return this.baseUrl;
    },

    loadSettings: function () {
      try {
        var stored = JSON.parse(localStorage.getItem(SETTINGS_KEY) || '{}');
        return Object.assign({}, DEFAULT_SETTINGS, stored);
      } catch (err) {
        return Object.assign({}, DEFAULT_SETTINGS);
      }
    },

    saveSettings: function (settings) {
      localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
      return settings;
    },

    request: function (path, options) {
      options = options || {};
      if (!this.baseUrl) {
        return Promise.reject(new Error('No server address set — open Settings and enter the desktop IP.'));
      }
      var controller = new AbortController();
      var timeout = setTimeout(function () { controller.abort(); }, options.timeoutMs || 15000);

      return fetch(this.baseUrl + path, {
        method: options.method || 'GET',
        headers: options.body ? { 'Content-Type': 'application/json' } : undefined,
        body: options.body ? JSON.stringify(options.body) : undefined,
        signal: controller.signal,
        mode: 'cors',
        cache: 'no-store'
      }).then(function (response) {
        return response.text().then(function (text) {
          var data = null;
          try { data = text ? JSON.parse(text) : null; } catch (err) { data = { detail: text }; }
          if (!response.ok) {
            var message = (data && data.detail) || ('HTTP ' + response.status);
            var error = new Error(typeof message === 'string' ? message : JSON.stringify(message));
            error.status = response.status;
            throw error;
          }
          return data;
        });
      }).catch(function (err) {
        if (err.name === 'AbortError') throw new Error('Request timed out — is the desktop server running?');
        throw err;
      }).finally(function () {
        clearTimeout(timeout);
      });
    },

    status: function () { return this.request('/status', { timeoutMs: 5000 }); },
    getCalibration: function () { return this.request('/calibration'); },
    calibrate: function (payload) { return this.request('/calibrate', { method: 'POST', body: payload }); },
    frame: function (payload) { return this.request('/frame', { method: 'POST', body: payload, timeoutMs: 20000 }); },
    verify: function (payload) { return this.request('/verify', { method: 'POST', body: payload, timeoutMs: 120000 }); },
    reset: function (payload) { return this.request('/reset', { method: 'POST', body: payload }); },
    nextTurn: function (payload) { return this.request('/turn/next', { method: 'POST', body: payload || {} }); },
    addDart: function (payload) { return this.request('/dart', { method: 'POST', body: payload }); },
    editDart: function (payload) { return this.request('/dart', { method: 'PATCH', body: payload }); },
    undoDart: function () { return this.request('/dart/undo', { method: 'POST', body: {} }); }
  };

  /* Exponential backoff around any promise-returning call, so a phone that
   * wanders out of Wi-Fi range recovers on its own instead of going dead. */
  Api.withRetry = function (fn, attempts, baseDelayMs) {
    attempts = attempts || 3;
    baseDelayMs = baseDelayMs || 500;
    return new Promise(function (resolve, reject) {
      var attempt = 0;
      function run() {
        fn().then(resolve).catch(function (err) {
          attempt += 1;
          if (attempt >= attempts) { reject(err); return; }
          setTimeout(run, baseDelayMs * Math.pow(2, attempt - 1));
        });
      }
      run();
    });
  };

  global.Api = Api;
})(window);
