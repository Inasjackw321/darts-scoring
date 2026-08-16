/* Camera capture and client-side motion detection.
 *
 * Motion gating matters: without it the phone would POST a full frame several
 * times a second and the desktop would diff images of a board where nothing has
 * happened. Instead a tiny greyscale thumbnail is compared frame to frame, and
 * only a real change wakes the network up.
 */
(function (global) {
  'use strict';

  // A dart is a small object in a wide frame — it changes well under 1% of the
  // pixels. The thumbnail therefore has to be fine enough to register it at
  // all: at 64x48 a landed dart is only a handful of pixels and rounds away.
  var THUMB_W = 128;
  var THUMB_H = 96;
  var PIXEL_DELTA = 22; // per-pixel intensity change that counts as "changed"

  function Camera(videoEl, captureCanvas, motionCanvas) {
    this.video = videoEl;
    this.captureCanvas = captureCanvas;
    this.motionCanvas = motionCanvas;
    this.motionCanvas.width = THUMB_W;
    this.motionCanvas.height = THUMB_H;
    this.motionCtx = this.motionCanvas.getContext('2d', { willReadFrequently: true });
    this.previousThumb = null;
    this.stream = null;
    this.lastMotion = 0;
  }

  Camera.prototype.start = function () {
    var self = this;
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      return Promise.reject(new Error('This browser cannot access the camera. On iOS the page must be served over HTTPS or from localhost.'));
    }
    var constraints = {
      audio: false,
      video: {
        facingMode: { ideal: 'environment' },
        width: { ideal: 1280 },
        height: { ideal: 720 }
      }
    };
    return navigator.mediaDevices.getUserMedia(constraints).then(function (stream) {
      self.stream = stream;
      self.video.srcObject = stream;
      return self.video.play().catch(function () { /* autoplay policies: the muted+playsinline attrs cover this */ });
    }).then(function () {
      return self.ready();
    });
  };

  Camera.prototype.ready = function () {
    var video = this.video;
    if (video.readyState >= 2 && video.videoWidth) return Promise.resolve();
    return new Promise(function (resolve) {
      video.addEventListener('loadeddata', function handler() {
        video.removeEventListener('loadeddata', handler);
        resolve();
      });
    });
  };

  Camera.prototype.stop = function () {
    if (this.stream) {
      this.stream.getTracks().forEach(function (track) { track.stop(); });
      this.stream = null;
    }
    this.previousThumb = null;
  };

  Camera.prototype.isRunning = function () {
    return !!this.stream;
  };

  /* Fraction (0..1) of thumbnail pixels that changed since the last check. */
  Camera.prototype.motionLevel = function () {
    if (!this.video.videoWidth) return 0;
    this.motionCtx.drawImage(this.video, 0, 0, THUMB_W, THUMB_H);
    var current = this.motionCtx.getImageData(0, 0, THUMB_W, THUMB_H).data;
    if (!this.previousThumb) {
      this.previousThumb = new Uint8ClampedArray(current);
      return 0;
    }
    var changed = 0;
    var total = THUMB_W * THUMB_H;
    for (var i = 0; i < current.length; i += 4) {
      var nowGray = (current[i] * 3 + current[i + 1] * 6 + current[i + 2]) / 10;
      var wasGray = (this.previousThumb[i] * 3 + this.previousThumb[i + 1] * 6 + this.previousThumb[i + 2]) / 10;
      if (Math.abs(nowGray - wasGray) > PIXEL_DELTA) changed += 1;
    }
    this.previousThumb.set(current);
    this.lastMotion = changed / total;
    return this.lastMotion;
  };

  /* Reset the motion baseline — call after a capture so the settling frame
   * that follows a throw doesn't immediately re-trigger. */
  Camera.prototype.resetMotion = function () {
    this.previousThumb = null;
  };

  /* Grab a full-resolution JPEG data URL of the current video frame. */
  Camera.prototype.capture = function (maxWidth, quality) {
    maxWidth = maxWidth || 1280;
    var width = this.video.videoWidth;
    var height = this.video.videoHeight;
    if (!width || !height) return null;
    var scale = Math.min(1, maxWidth / width);
    this.captureCanvas.width = Math.round(width * scale);
    this.captureCanvas.height = Math.round(height * scale);
    var ctx = this.captureCanvas.getContext('2d');
    ctx.drawImage(this.video, 0, 0, this.captureCanvas.width, this.captureCanvas.height);
    return this.captureCanvas.toDataURL('image/jpeg', quality || 0.85);
  };

  Camera.prototype.size = function () {
    return { width: this.captureCanvas.width, height: this.captureCanvas.height };
  };

  global.Camera = Camera;
})(window);
