/**
 * Neural Map — Canvas-based organic/biological neuron visualization.
 *
 * Neurons rendered as glowing brain cells with curved dendrite connections.
 * Uses d3-force for layout, Canvas for rendering.
 */
(function () {
  'use strict';

  var graphContainer = document.getElementById('graph-container');
  var detailPanel    = document.getElementById('detail-panel');
  var detailLabel    = document.getElementById('detail-label');
  var detailDesc     = document.getElementById('detail-description');
  var detailCount    = document.getElementById('detail-count');
  var detailWeight   = document.getElementById('detail-weight');
  var detailConfidence = document.getElementById('detail-confidence');
  var detailDataNote = document.getElementById('detail-data-note');
  var detailEvidence = document.getElementById('detail-evidence');
  var detailEntries  = document.getElementById('detail-entries');
  var btnDiscuss     = document.getElementById('btn-discuss');
  var btnAnalyze     = document.getElementById('btn-analyze');
  var analyzeStatus  = document.getElementById('analyze-status');
  var statusBar      = document.getElementById('status-bar');
  var detailClose    = document.getElementById('detail-close');

  var currentClusterId = null;
  var simulation = null;
  var canvas, ctx;
  var dpr = window.devicePixelRatio || 1;
  var nodes = [];
  var edges = [];
  var hoveredNode = null;
  var activeNode = null;
  var dragNode = null;
  var dragOffsetX = 0, dragOffsetY = 0;
  var animFrame = null;
  var time = 0;

  // ── Theme color resolution ─────────────────────────────────
  // Reads CSS variables set by the customization module. Each value
  // is cached for the page lifetime — colors only change on reload,
  // which is consistent with how the user interacts with these pages
  // (set colors on /customization/, then navigate here to see them).
  function cssVar(name, fallback) {
    var v = getComputedStyle(document.documentElement)
              .getPropertyValue('--' + name).trim();
    return v || fallback;
  }
  // Parse #rgb / #rrggbb / rgb()/rgba() into [r, g, b] (0–255).
  // Used to recompose `rgba(r,g,b,alpha)` strings where the legacy
  // code applies dynamic alpha — keeps the pulsing/glow effects intact
  // while letting users theme the underlying base color.
  function parseRgb(css) {
    if (!css) return [0, 0, 0];
    css = css.trim();
    if (css.charAt(0) === '#') {
      if (css.length === 4) {
        return [css.charAt(1) + css.charAt(1),
                css.charAt(2) + css.charAt(2),
                css.charAt(3) + css.charAt(3)]
               .map(function (c) { return parseInt(c, 16); });
      }
      return [css.substr(1, 2), css.substr(3, 2), css.substr(5, 2)]
             .map(function (c) { return parseInt(c, 16); });
    }
    var m = css.match(/rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/);
    return m ? [parseInt(m[1]), parseInt(m[2]), parseInt(m[3])] : [0, 0, 0];
  }
  function withAlpha(rgb, alpha) {
    return 'rgba(' + rgb[0] + ',' + rgb[1] + ',' + rgb[2] + ',' + alpha + ')';
  }
  var THEME = null;
  function resolveTheme() {
    THEME = {
      edgeRgb:   parseRgb(cssVar('neural-edge-color', 'rgba(0,0,0,0.25)')),
      nodeRgb:   parseRgb(cssVar('neural-node-color', 'rgb(40,40,40)')),
      activeRgb: parseRgb(cssVar('neural-node-active-color', '#009afa')),
      glowRgb:   parseRgb(cssVar('neural-glow-color', 'rgb(0,154,250)')),
      labelColor: cssVar('text-color', '#444'),
    };
    THEME.activeCss = 'rgb(' + THEME.activeRgb.join(',') + ')';
  }

  // ── Load graph data ────────────────────────────────────────────
  function loadGraph() {
    statusBar.textContent = 'Загрузка...';
    fetch('/deep-mind/api/graph')
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.status === 'empty') {
          statusBar.textContent = '';
          showEmpty();
          return;
        }
        statusBar.textContent = '';
        renderGraph(data);
      })
      .catch(function (e) {
        statusBar.textContent = 'Ошибка загрузки: ' + e.message;
      });
  }

  function showEmpty() {
    graphContainer.innerHTML =
      '<div class="empty-state">Нет данных для визуализации.<br>Нажмите «Проанализировать».</div>';
  }

  // ── Radius scale ─────────────────────────────────────────────
  function rScale(size, maxSize) {
    var minR = 12, maxR = 44;
    return minR + (maxR - minR) * Math.sqrt(size / (maxSize || 1));
  }

  // ── Canvas setup ─────────────────────────────────────────────
  function renderGraph(data) {
    graphContainer.innerHTML = '';
    if (simulation) simulation.stop();
    if (animFrame) cancelAnimationFrame(animFrame);
    resolveTheme();

    var W = graphContainer.clientWidth;
    var H = graphContainer.clientHeight;

    canvas = document.createElement('canvas');
    canvas.style.width = W + 'px';
    canvas.style.height = H + 'px';
    canvas.width = W * dpr;
    canvas.height = H * dpr;
    graphContainer.appendChild(canvas);
    ctx = canvas.getContext('2d');
    ctx.scale(dpr, dpr);

    nodes = data.nodes;
    edges = data.edges;

    var maxSize = 1;
    nodes.forEach(function (n) { if (n.size > maxSize) maxSize = n.size; });
    nodes.forEach(function (n) {
      n.r = rScale(n.size, maxSize);
      // Phase offset for pulsation
      n.phase = Math.random() * Math.PI * 2;
    });

    // ── d3-force simulation ──────────────────────────────────
    // Force parameters scale down with node count: with many neurons,
    // the cumulative repulsion energy is huge and any disturbance
    // propagates as a shock wave to all neighbours. We dampen this:
    //   - charge weaker and shorter-range
    //   - velocityDecay higher (more damping per tick)
    //   - alphaDecay slightly higher (smoother initial convergence)
    //   - collision padding smaller (less crowding pressure)
    var nodeCount = nodes.length;
    // Scale charge strength inversely with sqrt(N): -1200 was tuned for
    // ~10 nodes; with 33 the perceived "force per node" should stay similar.
    var chargeStrength = -800 * Math.sqrt(10 / Math.max(10, nodeCount));
    // Distance cap also shrinks so each neuron only "feels" closer ones.
    var chargeMaxDist = 700;

    simulation = d3.forceSimulation(nodes)
      .alphaDecay(0.035)        // smoother initial layout convergence
      .velocityDecay(0.55)      // more damping (default 0.4) — kills jitter
      .force('link', d3.forceLink(edges)
        .id(function (d) { return d.id; })
        .distance(function (d) { return 400 + 200 * (1 - d.strength); })
        .strength(function (d) { return d.strength * 0.15; })
      )
      .force('charge', d3.forceManyBody()
        .strength(chargeStrength)
        .distanceMax(chargeMaxDist))
      .force('center', d3.forceCenter(W / 2, H / 2).strength(0.02))
      .force('collision', d3.forceCollide().radius(function (d) {
        return d.r + 35;        // was r+80 — too aggressive at 33+ nodes
      }))
      .on('tick', function () {
        // Clamp positions
        nodes.forEach(function (n) {
          n.x = Math.max(n.r + 10, Math.min(W - n.r - 10, n.x));
          n.y = Math.max(n.r + 10, Math.min(H - n.r - 10, n.y));
        });
      });

    // Gentle floating for unpinned nodes — very small kicks so the map
    // breathes without the whole network reorganising every interval.
    setInterval(function () {
      nodes.forEach(function (n) {
        if (n.fx == null) {
          n.vx += (Math.random() - 0.5) * 0.05;
          n.vy += (Math.random() - 0.5) * 0.05;
        }
      });
      simulation.alpha(0.005).restart();
    }, 8000);

    // ── Mouse / touch events ─────────────────────────────────
    canvas.addEventListener('mousemove', onMouseMove);
    canvas.addEventListener('mousedown', onMouseDown);
    canvas.addEventListener('mouseup', onMouseUp);
    canvas.addEventListener('dblclick', onDblClick);
    canvas.addEventListener('click', onClick);
    canvas.style.cursor = 'default';

    // ── Animation loop ───────────────────────────────────────
    function animate() {
      time += 0.016; // ~60fps
      draw(W, H);
      animFrame = requestAnimationFrame(animate);
    }
    animate();
  }

  // ── Find node under cursor ─────────────────────────────────
  function nodeAt(x, y) {
    // Check in reverse order (top-most first)
    for (var i = nodes.length - 1; i >= 0; i--) {
      var n = nodes[i];
      var dx = x - n.x;
      var dy = y - n.y;
      if (dx * dx + dy * dy <= (n.r + 4) * (n.r + 4)) return n;
    }
    return null;
  }

  function canvasXY(e) {
    var rect = canvas.getBoundingClientRect();
    return { x: e.clientX - rect.left, y: e.clientY - rect.top };
  }

  // ── Mouse handlers ─────────────────────────────────────────
  function onMouseMove(e) {
    var p = canvasXY(e);
    if (dragNode) {
      // Update the pinned position only. The simulation is already kept
      // warm by the alphaTarget set in onMouseDown — calling
      // simulation.alpha(0.3).restart() here used to inject energy 60+
      // times per second on every cursor pixel, which is what made
      // neighbouring nodes snap violently. Letting the existing
      // alphaTarget-warmed simulation pick up the new fx/fy on the next
      // tick is dramatically smoother.
      dragNode.fx = p.x;
      dragNode.fy = p.y;
      return;
    }
    var h = nodeAt(p.x, p.y);
    if (h !== hoveredNode) {
      hoveredNode = h;
      canvas.style.cursor = h ? 'pointer' : 'default';
    }
  }

  function onMouseDown(e) {
    var p = canvasXY(e);
    var n = nodeAt(p.x, p.y);
    if (n) {
      dragNode = n;
      dragNode.fx = n.x;
      dragNode.fy = n.y;
      n._pinned = true;
      // 0.1 instead of the previous 0.3 — keeps the sim warm enough to
      // adjust neighbours during drag, but low enough that with strong
      // charge + 30+ nodes, the shock wave from a moved neuron stays
      // visible-but-gentle rather than explosive.
      simulation.alphaTarget(0.1).restart();
      e.preventDefault();
    }
  }

  function onMouseUp(e) {
    if (dragNode) {
      simulation.alphaTarget(0);
      // Keep pinned (sticky drag)
      dragNode = null;
    }
  }

  function onClick(e) {
    var p = canvasXY(e);
    var n = nodeAt(p.x, p.y);
    if (n) {
      activeNode = n;
      showDetail(n);
    } else {
      activeNode = null;
      hideDetail();
    }
  }

  function onDblClick(e) {
    var p = canvasXY(e);
    var n = nodeAt(p.x, p.y);
    if (n) {
      // Unpin
      n.fx = null;
      n.fy = null;
      n._pinned = false;
      simulation.alpha(0.1).restart();
      e.preventDefault();
    }
  }

  // ── Drawing ────────────────────────────────────────────────
  function draw(W, H) {
    ctx.clearRect(0, 0, W, H);

    // Draw dendrite connections
    edges.forEach(function (e) {
      drawDendrite(e);
    });

    // Draw neurons
    nodes.forEach(function (n) {
      drawNeuron(n, n === hoveredNode, n === activeNode);
    });

    // Draw labels
    nodes.forEach(function (n) {
      drawLabel(n, n === hoveredNode || n === activeNode);
    });
  }

  function drawDendrite(edge) {
    var s = edge.source;
    var t = edge.target;
    if (!s.x || !t.x) return;

    var strength = edge.strength || 0.5;
    var alpha = 0.08 + strength * 0.25;

    // Curved path — offset midpoint perpendicular to the line
    var mx = (s.x + t.x) / 2;
    var my = (s.y + t.y) / 2;
    var dx = t.x - s.x;
    var dy = t.y - s.y;
    var len = Math.sqrt(dx * dx + dy * dy) || 1;
    // Perpendicular offset — gentle curve
    var curvature = 0.15 + Math.sin(time * 0.3 + s.x * 0.01) * 0.05;
    var offsetX = -dy / len * len * curvature;
    var offsetY = dx / len * len * curvature;
    var cpx = mx + offsetX;
    var cpy = my + offsetY;

    ctx.beginPath();
    ctx.moveTo(s.x, s.y);
    ctx.quadraticCurveTo(cpx, cpy, t.x, t.y);
    ctx.strokeStyle = withAlpha(THEME.edgeRgb, alpha);
    ctx.lineWidth = 0.5 + strength * 1;
    ctx.stroke();

    // Tiny synaptic dots along the dendrite
    var dotCount = Math.floor(strength * 3) + 1;
    for (var i = 1; i <= dotCount; i++) {
      var t_ = i / (dotCount + 1);
      // Point on quadratic bezier
      var px = (1 - t_) * (1 - t_) * s.x + 2 * (1 - t_) * t_ * cpx + t_ * t_ * t.x;
      var py = (1 - t_) * (1 - t_) * s.y + 2 * (1 - t_) * t_ * cpy + t_ * t_ * t.y;
      // Pulsating dot
      var dotAlpha = 0.1 + 0.15 * Math.sin(time * 1.5 + i * 2 + s.x * 0.1);
      ctx.beginPath();
      ctx.arc(px, py, 1.5, 0, Math.PI * 2);
      ctx.fillStyle = withAlpha(THEME.edgeRgb, dotAlpha);
      ctx.fill();
    }
  }

  function drawNeuron(n, hovered, active) {
    var r = n.r;
    var w = n.weight || 0.5;

    // Pulsation: stronger for high-weight nodes
    var pulseAmp = w > 0.7 ? 3 : 1.5;
    var pulseSpeed = 0.8 + w * 0.6;
    var pulse = Math.sin(time * pulseSpeed + n.phase) * pulseAmp;
    var drawR = r + pulse;

    // Outer glow
    var glowAlpha = 0.04 + w * 0.06;
    if (hovered || active) glowAlpha = 0.12;
    var gradient = ctx.createRadialGradient(n.x, n.y, drawR * 0.3, n.x, n.y, drawR * 2.2);
    if (active) {
      gradient.addColorStop(0, withAlpha(THEME.glowRgb, glowAlpha * 2.5));
      gradient.addColorStop(1, withAlpha(THEME.glowRgb, 0));
    } else if (hovered) {
      gradient.addColorStop(0, withAlpha(THEME.glowRgb, glowAlpha * 1.5));
      gradient.addColorStop(1, withAlpha(THEME.glowRgb, 0));
    } else {
      gradient.addColorStop(0, withAlpha(THEME.edgeRgb, glowAlpha));
      gradient.addColorStop(1, withAlpha(THEME.edgeRgb, 0));
    }
    ctx.beginPath();
    ctx.arc(n.x, n.y, drawR * 2.2, 0, Math.PI * 2);
    ctx.fillStyle = gradient;
    ctx.fill();

    // Cell body — organic shape (slightly irregular circle)
    ctx.beginPath();
    var steps = 32;
    for (var i = 0; i <= steps; i++) {
      var angle = (i / steps) * Math.PI * 2;
      // Subtle irregularity
      var irregularity = 1 + Math.sin(angle * 3 + n.phase) * 0.04
                           + Math.sin(angle * 5 + n.phase * 2) * 0.02;
      var cr = drawR * irregularity;
      var cx = n.x + Math.cos(angle) * cr;
      var cy = n.y + Math.sin(angle) * cr;
      if (i === 0) ctx.moveTo(cx, cy);
      else ctx.lineTo(cx, cy);
    }
    ctx.closePath();

    // Fill — themed via CSS variables. Hover keeps a fixed mid-grey to
    // give a clear "darken" feedback regardless of base node color.
    if (active) {
      ctx.fillStyle = THEME.activeCss;
    } else if (hovered) {
      ctx.fillStyle = withAlpha(THEME.nodeRgb, 1.0);
    } else {
      // Darker for heavier weight: lerp the themed node color toward
      // black by `(1-w) * 0.3` so high-weight nodes are slightly darker.
      var lerp = (1 - w) * 0.3;
      var rr = Math.round(THEME.nodeRgb[0] * (1 - lerp));
      var gg = Math.round(THEME.nodeRgb[1] * (1 - lerp));
      var bb = Math.round(THEME.nodeRgb[2] * (1 - lerp));
      ctx.fillStyle = 'rgb(' + rr + ',' + gg + ',' + bb + ')';
    }
    ctx.fill();

    // Nucleus — lighter inner circle
    var nucleusR = drawR * 0.35;
    var nGrad = ctx.createRadialGradient(
      n.x - nucleusR * 0.3, n.y - nucleusR * 0.3, nucleusR * 0.1,
      n.x, n.y, nucleusR
    );
    if (active) {
      nGrad.addColorStop(0, 'rgba(255, 255, 255, 0.35)');
      nGrad.addColorStop(1, 'rgba(255, 255, 255, 0.05)');
    } else {
      nGrad.addColorStop(0, 'rgba(255, 255, 255, 0.2)');
      nGrad.addColorStop(1, 'rgba(255, 255, 255, 0.02)');
    }
    ctx.beginPath();
    ctx.arc(n.x, n.y, nucleusR, 0, Math.PI * 2);
    ctx.fillStyle = nGrad;
    ctx.fill();

    // Small dendrite stubs radiating from the cell
    drawDendriteStubs(n, drawR, active || hovered);

    // Pinned indicator — small ring (uses active/glow color so it
    // visually relates to "selected" state)
    if (n._pinned) {
      ctx.beginPath();
      ctx.arc(n.x, n.y, drawR + 3, 0, Math.PI * 2);
      ctx.strokeStyle = withAlpha(THEME.activeRgb, 0.4);
      ctx.lineWidth = 1;
      ctx.stroke();
    }
  }

  function drawDendriteStubs(n, r, highlighted) {
    // Small organic projections from the neuron body
    var count = Math.min(Math.floor(n.size / 2) + 3, 8);
    var alpha = highlighted ? 0.5 : 0.25;

    for (var i = 0; i < count; i++) {
      var angle = (i / count) * Math.PI * 2 + n.phase;
      var len = r * (0.4 + Math.sin(time * 0.5 + i + n.phase) * 0.15);
      var startX = n.x + Math.cos(angle) * r;
      var startY = n.y + Math.sin(angle) * r;
      var endX = n.x + Math.cos(angle) * (r + len);
      var endY = n.y + Math.sin(angle) * (r + len);
      // Slight curve
      var cpX = (startX + endX) / 2 + Math.sin(angle + 1) * len * 0.3;
      var cpY = (startY + endY) / 2 + Math.cos(angle + 1) * len * 0.3;

      ctx.beginPath();
      ctx.moveTo(startX, startY);
      ctx.quadraticCurveTo(cpX, cpY, endX, endY);
      ctx.strokeStyle = withAlpha(THEME.edgeRgb, alpha);
      ctx.lineWidth = 1;
      ctx.stroke();

      // Tiny terminal bulb
      ctx.beginPath();
      ctx.arc(endX, endY, 1.5, 0, Math.PI * 2);
      ctx.fillStyle = withAlpha(THEME.edgeRgb, alpha * 0.8);
      ctx.fill();
    }
  }

  function drawLabel(n, highlighted) {
    var label = n.label.length > 25 ? n.label.substring(0, 23) + '...' : n.label;
    ctx.font = (highlighted ? 'bold ' : '') + '12px "Times New Roman", Times, serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    ctx.fillStyle = highlighted ? THEME.activeCss : THEME.labelColor;
    ctx.fillText(label, n.x, n.y + n.r + 16);
  }

  // ── Detail panel ───────────────────────────────────────────────
  function showDetail(d) {
    currentClusterId = d.id;
    detailLabel.textContent = d.label;
    detailDesc.textContent = d.description || '';
    detailCount.textContent = d.size + ' записей';
    detailWeight.textContent = 'вес: ' + Math.round(d.weight * 100) + '%';
    if (detailConfidence) {
      detailConfidence.textContent = '\u0443\u0432\u0435\u0440\u0435\u043d\u043d\u043e\u0441\u0442\u044c: ' + (d.confidence_label || '\u2014');
    }
    if (detailDataNote) {
      detailDataNote.textContent = d.data_note || '';
      detailDataNote.style.display = d.data_note ? 'block' : 'none';
    }
    if (detailEvidence) {
      detailEvidence.innerHTML = '';
      if (d.evidence && d.evidence.length) {
        var title = document.createElement('div');
        title.className = 'detail-evidence-title';
        title.textContent = '\u041e\u0441\u043d\u043e\u0432\u0430\u043d\u0438\u0435';
        detailEvidence.appendChild(title);
        d.evidence.forEach(function (ev) {
          var item = document.createElement('div');
          item.className = 'detail-evidence-item';
          var meta = '<span class="detail-evidence-meta">' + ev.date + '</span>';
          if (ev.rating != null) {
            meta += '<span class="detail-evidence-meta">' + ev.rating + '/10</span>';
          }
          item.innerHTML = meta + '<span class="detail-evidence-snippet">' + escapeHtml(ev.snippet) + '</span>';
          detailEvidence.appendChild(item);
        });
        detailEvidence.style.display = 'block';
      } else {
        detailEvidence.style.display = 'none';
      }
    }
    detailPanel.classList.toggle('low-data', !!d.low_data);

    detailEntries.innerHTML = '';
    (d.entries || []).forEach(function (e) {
      var div = document.createElement('div');
      div.className = 'detail-entry';
      div.innerHTML =
        '<span class="entry-date">' + e.date + '</span>' +
        '<span class="entry-rating">' + e.rating + '/10</span>' +
        '<p class="entry-note">' + escapeHtml(e.note) + '</p>';
      detailEntries.appendChild(div);
    });

    detailPanel.classList.remove('hidden');
  }

  function hideDetail() {
    detailPanel.classList.add('hidden');
    detailPanel.classList.remove('low-data');
    currentClusterId = null;
    activeNode = null;
  }

  if (detailClose) detailClose.addEventListener('click', hideDetail);

  // ── Chat handoff ───────────────────────────────────────────────
  if (btnDiscuss) {
    btnDiscuss.addEventListener('click', function () {
      if (!currentClusterId) return;
      window.location.href = '/assistant/?topic=' + currentClusterId;
    });
  }

  // ── Background analysis ────────────────────────────────────────
  var pollTimer = null;

  if (btnAnalyze) {
    btnAnalyze.addEventListener('click', function () {
      btnAnalyze.disabled = true;
      analyzeStatus.textContent = 'Запуск анализа...';
      fetch('/deep-mind/api/analyze', { method: 'POST' })
        .then(function (r) { return r.json(); })
        .then(function () { pollStatus(); })
        .catch(function (e) {
          analyzeStatus.textContent = 'Ошибка: ' + e.message;
          btnAnalyze.disabled = false;
        });
    });
  }

  function pollStatus() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(function () {
      fetch('/deep-mind/api/status')
        .then(function (r) { return r.json(); })
        .then(function (s) {
          if (s.running) {
            analyzeStatus.textContent = formatStage(s.stage) + ' (' + s.progress + '%)';
          } else {
            clearInterval(pollTimer);
            pollTimer = null;
            if (btnAnalyze) btnAnalyze.disabled = false;
            if (s.stage === 'done') {
              var total = (s.clusters_found != null) ? s.clusters_found : 0;
              var visible = (s.clusters_visible != null) ? s.clusters_visible : total;
              if (visible !== total && total > 0) {
                analyzeStatus.textContent = 'Готово. Тем: ' + visible + ' из ' + total;
              } else {
                analyzeStatus.textContent = 'Готово. Найдено тем: ' + visible;
              }
              loadGraph();
            } else if (s.stage === 'error') {
              analyzeStatus.textContent = 'Ошибка: ' + s.error;
            } else {
              analyzeStatus.textContent = '';
            }
          }
        });
    }, 1500);
  }

  function formatStage(stage) {
    if (!stage) return 'Анализ...';
    if (stage === 'clustering') return 'Кластеризация...';
    if (stage === 'loading_llm') return 'Загрузка модели...';
    if (stage.startsWith('naming:')) {
      var parts = stage.split(':')[1].split('/');
      return 'Именование тем: ' + parts[0] + ' из ' + parts[1];
    }
    return stage;
  }

  // ── Helpers ────────────────────────────────────────────────────
  function escapeHtml(str) {
    return (str || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }

  // ── Resize handler ────────────────────────────────────────────
  window.addEventListener('resize', function () {
    if (!canvas) return;
    var W = graphContainer.clientWidth;
    var H = graphContainer.clientHeight;
    canvas.style.width = W + 'px';
    canvas.style.height = H + 'px';
    canvas.width = W * dpr;
    canvas.height = H * dpr;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.scale(dpr, dpr);
    if (simulation) {
      simulation.force('center', d3.forceCenter(W / 2, H / 2).strength(0.04));
      // Lower alpha kick on resize — 0.3 caused the same shock-wave
      // problem when many nodes are present. 0.1 still re-centers the
      // graph cleanly without violent reorganisation.
      simulation.alpha(0.1).restart();
    }
  });

  // ── Init ───────────────────────────────────────────────────────
  loadGraph();
  fetch('/deep-mind/api/status')
    .then(function (r) { return r.json(); })
    .then(function (s) { if (s.running) pollStatus(); });
}());
