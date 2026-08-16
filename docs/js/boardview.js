/* SVG dartboard diagram.
 *
 * Doubles as the calibration sanity check: if a dart marker lands somewhere
 * you didn't throw it, the homography is off, not the scoring maths.
 * Board space is millimetres with +y up, so the SVG flips y.
 */
(function (global) {
  'use strict';

  var R = {
    innerBull: 6.35,
    outerBull: 15.9,
    trebleInner: 99,
    trebleOuter: 107,
    doubleInner: 162,
    doubleOuter: 170
  };
  var ORDER = [20, 1, 18, 4, 13, 6, 10, 15, 2, 17, 3, 19, 7, 16, 8, 11, 14, 9, 12, 5];
  var ARC = 18;
  var SVG_NS = 'http://www.w3.org/2000/svg';

  function polar(radius, angleDeg) {
    var a = angleDeg * Math.PI / 180;
    return [radius * Math.cos(a), -radius * Math.sin(a)]; // negate y: SVG grows downward
  }

  function wedgePath(rInner, rOuter, startDeg, endDeg) {
    var p1 = polar(rOuter, startDeg);
    var p2 = polar(rOuter, endDeg);
    var p3 = polar(rInner, endDeg);
    var p4 = polar(rInner, startDeg);
    // Sweep flag 0 because increasing maths-angle runs anticlockwise, which is
    // clockwise once y is flipped for SVG.
    return 'M' + p1[0] + ',' + p1[1] +
           ' A' + rOuter + ',' + rOuter + ' 0 0 0 ' + p2[0] + ',' + p2[1] +
           ' L' + p3[0] + ',' + p3[1] +
           ' A' + rInner + ',' + rInner + ' 0 0 1 ' + p4[0] + ',' + p4[1] + ' Z';
  }

  function el(name, attrs) {
    var node = document.createElementNS(SVG_NS, name);
    Object.keys(attrs || {}).forEach(function (key) { node.setAttribute(key, attrs[key]); });
    return node;
  }

  var BoardView = {
    render: function (container, darts, options) {
      options = options || {};
      darts = darts || [];
      container.innerHTML = '';

      var svg = el('svg', { viewBox: '-195 -195 390 390', role: 'img', 'aria-label': 'Dartboard with detected darts' });
      svg.appendChild(el('circle', { cx: 0, cy: 0, r: 190, fill: '#10151a' }));
      svg.appendChild(el('circle', { cx: 0, cy: 0, r: R.doubleOuter, fill: '#1b1b1b' }));

      ORDER.forEach(function (number, index) {
        var centre = 90 - index * ARC;
        var start = centre + ARC / 2;
        var end = centre - ARC / 2;
        var dark = index % 2 === 0;
        var singleFill = dark ? '#0d0d0d' : '#e9dcc0';
        var ringFill = dark ? '#c8352c' : '#1e7d47';

        svg.appendChild(el('path', { d: wedgePath(R.trebleOuter, R.doubleInner, start, end), fill: singleFill }));
        svg.appendChild(el('path', { d: wedgePath(R.outerBull, R.trebleInner, start, end), fill: singleFill }));
        svg.appendChild(el('path', { d: wedgePath(R.trebleInner, R.trebleOuter, start, end), fill: ringFill }));
        svg.appendChild(el('path', { d: wedgePath(R.doubleInner, R.doubleOuter, start, end), fill: ringFill }));

        var label = polar(181, centre);
        var text = el('text', {
          x: label[0], y: label[1] + 6,
          fill: '#93a1b0', 'font-size': 17, 'text-anchor': 'middle', 'font-family': 'sans-serif'
        });
        text.textContent = String(number);
        svg.appendChild(text);
      });

      svg.appendChild(el('circle', { cx: 0, cy: 0, r: R.outerBull, fill: '#1e7d47' }));
      svg.appendChild(el('circle', { cx: 0, cy: 0, r: R.innerBull, fill: '#c8352c' }));

      darts.forEach(function (dart, index) {
        if (typeof dart.x_mm !== 'number' || typeof dart.y_mm !== 'number') return;
        var x = dart.x_mm;
        var y = -dart.y_mm;
        var colour = dart.low_confidence ? '#e2b53f' : (dart.source === 'manual' ? '#6aa9ff' : '#35d07f');
        var group = el('g', {});
        group.appendChild(el('circle', { cx: x, cy: y, r: 7, fill: 'none', stroke: '#000', 'stroke-width': 3.5 }));
        group.appendChild(el('circle', { cx: x, cy: y, r: 7, fill: 'none', stroke: colour, 'stroke-width': 2 }));
        group.appendChild(el('circle', { cx: x, cy: y, r: 2, fill: colour }));
        var tag = el('text', {
          x: x, y: y - 11, fill: colour, 'font-size': 15, 'text-anchor': 'middle',
          'font-family': 'sans-serif', 'paint-order': 'stroke', stroke: '#000', 'stroke-width': 3
        });
        tag.textContent = (index + 1) + ': ' + (dart.label || '');
        group.appendChild(tag);
        svg.appendChild(group);
      });

      if (options.tips) {
        // Raw pixel-space tips that did not become darts (duplicates, off-board).
        options.tips.forEach(function (tip) {
          if (typeof tip.x_mm !== 'number') return;
          svg.appendChild(el('circle', {
            cx: tip.x_mm, cy: -tip.y_mm, r: 4, fill: 'none', stroke: '#93a1b0',
            'stroke-width': 1, 'stroke-dasharray': '2 2'
          }));
        });
      }

      container.appendChild(svg);
    },

    radii: R,
    order: ORDER
  };

  global.BoardView = BoardView;
})(window);
