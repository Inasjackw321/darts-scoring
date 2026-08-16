/* Calibration UI: freeze a frame, tap the reference points, POST them.
 *
 * Clicks are recorded in the frozen image's own pixel coordinates (not CSS
 * pixels), because that is the space the server's homography is fitted in.
 */
(function (global) {
  'use strict';

  function Calibrator(canvas, options) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.points = [];
    this.frameDataUrl = null;
    this.frameImage = null;
    this.overlay = null;
    this.onChange = (options && options.onChange) || function () {};
    var self = this;
    canvas.addEventListener('click', function (event) { self._handleClick(event); });
  }

  Calibrator.prototype.expectedCount = function () {
    return (this.referencePoints || []).length || 4;
  };

  Calibrator.prototype.setReferencePoints = function (points) {
    this.referencePoints = points;
  };

  /* Freeze the given data URL as the calibration backdrop. */
  Calibrator.prototype.setFrame = function (dataUrl) {
    var self = this;
    this.frameDataUrl = dataUrl;
    this.points = [];
    this.overlay = null;
    return new Promise(function (resolve, reject) {
      var image = new Image();
      image.onload = function () {
        self.frameImage = image;
        self.canvas.width = image.naturalWidth;
        self.canvas.height = image.naturalHeight;
        self.redraw();
        self.onChange();
        resolve();
      };
      image.onerror = function () { reject(new Error('Could not load the captured frame')); };
      image.src = dataUrl;
    });
  };

  Calibrator.prototype._handleClick = function (event) {
    if (!this.frameImage) return;
    if (this.points.length >= this.expectedCount()) return;
    var rect = this.canvas.getBoundingClientRect();
    // Map CSS pixels back to the frame's native resolution.
    var x = (event.clientX - rect.left) * (this.canvas.width / rect.width);
    var y = (event.clientY - rect.top) * (this.canvas.height / rect.height);
    this.points.push([Math.round(x * 10) / 10, Math.round(y * 10) / 10]);
    this.redraw();
    this.onChange();
  };

  Calibrator.prototype.clearPoints = function () {
    this.points = [];
    this.overlay = null;
    this.redraw();
    this.onChange();
  };

  Calibrator.prototype.undoPoint = function () {
    this.points.pop();
    this.redraw();
    this.onChange();
  };

  Calibrator.prototype.setOverlay = function (outlinePx) {
    this.overlay = outlinePx;
    this.redraw();
  };

  Calibrator.prototype.redraw = function () {
    if (!this.frameImage) return;
    var ctx = this.ctx;
    ctx.drawImage(this.frameImage, 0, 0, this.canvas.width, this.canvas.height);
    var scale = Math.max(1, this.canvas.width / 640);

    if (this.overlay && this.overlay.length) {
      ctx.beginPath();
      this.overlay.forEach(function (point, index) {
        if (index === 0) ctx.moveTo(point[0], point[1]);
        else ctx.lineTo(point[0], point[1]);
      });
      ctx.closePath();
      ctx.strokeStyle = '#35d07f';
      ctx.lineWidth = 2 * scale;
      ctx.stroke();
    }

    var self = this;
    this.points.forEach(function (point, index) {
      ctx.beginPath();
      ctx.arc(point[0], point[1], 9 * scale, 0, Math.PI * 2);
      ctx.strokeStyle = '#e2b53f';
      ctx.lineWidth = 2.5 * scale;
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(point[0], point[1], 2 * scale, 0, Math.PI * 2);
      ctx.fillStyle = '#e2b53f';
      ctx.fill();
      ctx.font = (16 * scale) + 'px sans-serif';
      ctx.fillStyle = '#e2b53f';
      ctx.strokeStyle = '#000';
      ctx.lineWidth = 3 * scale;
      var label = String(index + 1);
      ctx.strokeText(label, point[0] + 12 * scale, point[1] - 10 * scale);
      ctx.fillText(label, point[0] + 12 * scale, point[1] - 10 * scale);
      void self;
    });
  };

  Calibrator.prototype.isComplete = function () {
    return this.points.length === this.expectedCount();
  };

  Calibrator.prototype.payload = function () {
    return {
      image_points: this.points,
      frame_width: this.canvas.width,
      frame_height: this.canvas.height,
      image: this.frameDataUrl
    };
  };

  global.Calibrator = Calibrator;
})(window);
