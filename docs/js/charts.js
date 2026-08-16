/* Charts, drawn as inline SVG. No libraries, no build step.
 *
 * Two forms, chosen by the job the data does:
 *   - progression: change over time -> lines, one per player, categorical hues
 *   - board:       magnitude over a fixed layout -> choropleth, one sequential hue
 *
 * The board deliberately is NOT a scatter of dart positions. Tapping "T20"
 * records a region, not a point, so plotting dots inside the segment would
 * invent precision the data does not have. Regions shaded by hit count say
 * exactly what is known and nothing more.
 */
(function (root, factory) {
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.DartsCharts = api;
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  var NS = 'http://www.w3.org/2000/svg';

  // Categorical hues, fixed order, stepped for a dark surface. Never cycled:
  // past four players the app falls back to small multiples rather than
  // inventing a fifth hue.
  var SERIES = ['#3987e5', '#d95926', '#199e70', '#c98500'];

  // Sequential ramp, one hue, low -> high against the dark surface.
  var RAMP = ['#104281', '#184f95', '#256abf', '#3987e5', '#5598e7', '#86b6ef', '#b7d3f6'];

  var INK = '#e8ece9';
  var INK_MUTED = '#93a09a';
  var GRID = '#3a4641';
  var SURFACE = '#141817';
  // Regions never hit need their own neutral: painting them the page colour
  // erases the board's shape and the chart stops reading as a dartboard.
  var EMPTY = '#212926';

  function el(name, attrs, text) {
    var node = document.createElementNS(NS, name);
    Object.keys(attrs || {}).forEach(function (k) { node.setAttribute(k, attrs[k]); });
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function seriesColour(index) {
    return SERIES[index % SERIES.length];
  }

  /* ------------------------------------------------------------------ *
   * Score progression
   * ------------------------------------------------------------------ */
  function progression(container, leg, options) {
    options = options || {};
    container.innerHTML = '';
    var series = (leg && leg.series) || [];
    if (!series.length) {
      container.appendChild(emptyNote('No turns played yet.'));
      return;
    }

    var W = 640, H = 260;
    var pad = { top: 18, right: 62, bottom: 30, left: 42 };
    var maxTurn = Math.max.apply(null, series.map(function (s) { return s.points.length - 1; }).concat([1]));
    var maxValue = Math.max.apply(null, series.map(function (s) {
      return Math.max.apply(null, s.points.map(function (p) { return p.value; }));
    }).concat([1]));

    var x = function (turn) {
      return pad.left + (turn / maxTurn) * (W - pad.left - pad.right);
    };
    var y = function (value) {
      return H - pad.bottom - (value / maxValue) * (H - pad.top - pad.bottom);
    };

    var svg = el('svg', {
      viewBox: '0 0 ' + W + ' ' + H,
      role: 'img',
      'aria-label': 'Score remaining after each turn'
    });
    svg.style.width = '100%';
    svg.style.height = 'auto';

    // Recessive grid: four horizontal rules, labelled.
    var ticks = 4;
    for (var i = 0; i <= ticks; i++) {
      var value = Math.round((maxValue / ticks) * i);
      var gy = y(value);
      svg.appendChild(el('line', {
        x1: pad.left, x2: W - pad.right, y1: gy, y2: gy,
        stroke: GRID, 'stroke-width': 1
      }));
      svg.appendChild(el('text', {
        x: pad.left - 8, y: gy + 4, fill: INK_MUTED, 'font-size': 11,
        'text-anchor': 'end', 'font-family': 'inherit'
      }, String(value)));
    }
    svg.appendChild(el('text', {
      x: (pad.left + W - pad.right) / 2, y: H - 6, fill: INK_MUTED, 'font-size': 11,
      'text-anchor': 'middle', 'font-family': 'inherit'
    }, 'turns'));

    series.forEach(function (s, index) {
      var colour = seriesColour(index);
      var d = s.points.map(function (p, i) {
        return (i === 0 ? 'M' : 'L') + x(p.turn) + ',' + y(p.value);
      }).join(' ');
      svg.appendChild(el('path', {
        d: d, fill: 'none', stroke: colour, 'stroke-width': 2,
        'stroke-linejoin': 'round', 'stroke-linecap': 'round'
      }));

      // Emphasised endpoint plus a direct label, so identity never rests on
      // colour alone.
      var last = s.points[s.points.length - 1];
      svg.appendChild(el('circle', {
        cx: x(last.turn), cy: y(last.value), r: 4,
        fill: colour, stroke: SURFACE, 'stroke-width': 2
      }));
      svg.appendChild(el('text', {
        x: x(last.turn) + 9, y: y(last.value) + 4, fill: INK, 'font-size': 12,
        'font-family': 'inherit'
      }, s.player));

      s.points.forEach(function (p) {
        var dot = el('circle', {
          cx: x(p.turn), cy: y(p.value), r: 9, fill: 'transparent',
          'pointer-events': 'all'
        });
        dot.appendChild(el('title', {},
          s.player + ' — turn ' + p.turn + ': ' + p.value + ' left'));
        svg.appendChild(dot);
      });
    });

    container.appendChild(svg);
    if (series.length >= 2) container.appendChild(legend(series.map(function (s, i) {
      return { label: s.player, colour: seriesColour(i) };
    })));
  }

  /* ------------------------------------------------------------------ *
   * Board heatmap
   * ------------------------------------------------------------------ */
  var ORDER = [20, 1, 18, 4, 13, 6, 10, 15, 2, 17, 3, 19, 7, 16, 8, 11, 14, 9, 12, 5];
  var R = { innerBull: 3.7, outerBull: 9.4, trebleInner: 58.2, trebleOuter: 62.9, doubleInner: 95.3, doubleOuter: 100 };

  function polar(radius, angleDeg) {
    var a = angleDeg * Math.PI / 180;
    return [radius * Math.cos(a), -radius * Math.sin(a)];
  }

  function wedge(rIn, rOut, a0, a1) {
    var p1 = polar(rOut, a0), p2 = polar(rOut, a1), p3 = polar(rIn, a1), p4 = polar(rIn, a0);
    return 'M' + p1 + ' A' + rOut + ',' + rOut + ' 0 0 0 ' + p2 +
           ' L' + p3 + ' A' + rIn + ',' + rIn + ' 0 0 1 ' + p4 + ' Z';
  }

  function shade(count, max) {
    if (!count) return null;                    // never hit: stays surface
    var t = max <= 1 ? 1 : (count - 1) / (max - 1);
    return RAMP[Math.min(RAMP.length - 1, Math.round(t * (RAMP.length - 1)))];
  }

  function boardHeatmap(container, board, options) {
    options = options || {};
    container.innerHTML = '';
    if (!board || !board.total) {
      container.appendChild(emptyNote('No darts thrown yet.'));
      return;
    }

    var svg = el('svg', {
      viewBox: '-118 -118 236 236', role: 'img',
      'aria-label': 'Dartboard shaded by how often each region was hit'
    });
    svg.style.width = '100%';
    svg.style.height = 'auto';

    function cell(path, count, name) {
      var fill = shade(count, board.max);
      var node = el('path', {
        d: path,
        fill: fill || EMPTY,
        stroke: GRID,
        'stroke-width': 0.5
      });
      node.appendChild(el('title', {}, name + ' — ' + (count || 0) +
        (count === 1 ? ' dart' : ' darts')));
      svg.appendChild(node);
    }

    ORDER.forEach(function (number, index) {
      var centre = 90 - index * 18;
      var a0 = centre + 9, a1 = centre - 9;
      var counts = board.cells;
      // The two single areas are one data cell: tapping "20" does not record
      // whether it landed inside or outside the treble ring, so both are
      // shaded from the same count rather than inventing a split.
      var singles = counts[number + ':1'];
      cell(wedge(R.outerBull, R.trebleInner, a0, a1), singles, 'Single ' + number);
      cell(wedge(R.trebleInner, R.trebleOuter, a0, a1), counts[number + ':3'], 'T' + number);
      cell(wedge(R.trebleOuter, R.doubleInner, a0, a1), singles, 'Single ' + number);
      cell(wedge(R.doubleInner, R.doubleOuter, a0, a1), counts[number + ':2'], 'D' + number);

      var pos = polar(110, centre);
      svg.appendChild(el('text', {
        x: pos[0], y: pos[1] + 4, fill: INK_MUTED, 'font-size': 10,
        'text-anchor': 'middle', 'font-family': 'inherit'
      }, String(number)));
    });

    // Bulls sit on top of the wedges.
    var outer = el('circle', {
      cx: 0, cy: 0, r: R.outerBull,
      fill: shade(board.cells['25:1'], board.max) || EMPTY,
      stroke: GRID, 'stroke-width': 0.5
    });
    outer.appendChild(el('title', {}, '25 — ' + (board.cells['25:1'] || 0) + ' darts'));
    svg.appendChild(outer);

    var inner = el('circle', {
      cx: 0, cy: 0, r: R.innerBull,
      fill: shade(board.cells['25:2'], board.max) || EMPTY,
      stroke: GRID, 'stroke-width': 0.5
    });
    inner.appendChild(el('title', {}, 'Bull — ' + (board.cells['25:2'] || 0) + ' darts'));
    svg.appendChild(inner);

    container.appendChild(svg);
    container.appendChild(rampLegend(board.max));
  }

  /* ------------------------------------------------------------------ *
   * Legends and helpers
   * ------------------------------------------------------------------ */
  function legend(entries) {
    var wrap = document.createElement('div');
    wrap.className = 'legend';
    entries.forEach(function (entry) {
      var item = document.createElement('span');
      item.className = 'legend-item';
      var swatch = document.createElement('span');
      swatch.className = 'legend-swatch';
      swatch.style.background = entry.colour;
      item.appendChild(swatch);
      item.appendChild(document.createTextNode(entry.label));
      wrap.appendChild(item);
    });
    return wrap;
  }

  function rampLegend(max) {
    var wrap = document.createElement('div');
    wrap.className = 'legend legend-ramp';
    var none = document.createElement('span');
    none.className = 'legend-step legend-step-empty';
    var noneCap = document.createElement('span');
    noneCap.className = 'legend-cap';
    noneCap.textContent = 'not hit';
    wrap.appendChild(none);
    wrap.appendChild(noneCap);

    var low = document.createElement('span');
    low.className = 'legend-cap';
    low.textContent = '1';
    wrap.appendChild(low);
    RAMP.forEach(function (colour) {
      var step = document.createElement('span');
      step.className = 'legend-step';
      step.style.background = colour;
      wrap.appendChild(step);
    });
    var high = document.createElement('span');
    high.className = 'legend-cap';
    high.textContent = max + (max === 1 ? ' dart' : ' darts');
    wrap.appendChild(high);
    return wrap;
  }

  function emptyNote(text) {
    var node = document.createElement('p');
    node.className = 'muted';
    node.textContent = text;
    return node;
  }

  return {
    progression: progression,
    boardHeatmap: boardHeatmap,
    seriesColour: seriesColour,
    SERIES: SERIES
  };
});
