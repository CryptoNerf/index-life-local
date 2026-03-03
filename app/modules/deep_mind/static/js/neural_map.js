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
    simulation = d3.forceSimulation(nodes)
      .force('link', d3.forceLink(edges)
        .id(function (d) { return d.id; })
        .distance(function (d) { return 400 + 200 * (1 - d.strength); })
        .strength(function (d) { return d.strength * 0.15; })
      )
      .force('charge', d3.forceManyBody().strength(-1200).distanceMax(1200))
      .force('center', d3.forceCenter(W / 2, H / 2).strength(0.02))
      .force('collision', d3.forceCollide().radius(function (d) {
        return d.r + 80;
      }))
      .on('tick', function () {
        // Clamp positions
        nodes.forEach(function (n) {
          n.x = Math.max(n.r + 10, Math.min(W - n.r - 10, n.x));
          n.y = Math.max(n.r + 10, Math.min(H - n.r - 10, n.y));
        });
      });

    // Gentle floating for unpinned nodes
    setInterval(function () {
      nodes.forEach(function (n) {
        if (n.fx == null) {
          n.vx += (Math.random() - 0.5) * 0.15;
          n.vy += (Math.random() - 0.5) * 0.15;
        }
      });
      simulation.alpha(0.015).restart();
    }, 5000);

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
      dragNode.fx = p.x;
      dragNode.fy = p.y;
      simulation.alpha(0.3).restart();
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
      simulation.alphaTarget(0.3).restart();
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
    ctx.strokeStyle = 'rgba(0, 0, 0, ' + alpha + ')';
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
      ctx.fillStyle = 'rgba(0, 0, 0, ' + dotAlpha + ')';
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
      gradient.addColorStop(0, 'rgba(0, 154, 250, ' + (glowAlpha * 2.5) + ')');
      gradient.addColorStop(1, 'rgba(0, 154, 250, 0)');
    } else if (hovered) {
      gradient.addColorStop(0, 'rgba(0, 154, 250, ' + (glowAlpha * 1.5) + ')');
      gradient.addColorStop(1, 'rgba(0, 154, 250, 0)');
    } else {
      gradient.addColorStop(0, 'rgba(0, 0, 0, ' + glowAlpha + ')');
      gradient.addColorStop(1, 'rgba(0, 0, 0, 0)');
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

    // Fill
    if (active) {
      ctx.fillStyle = '#009AFA';
    } else if (hovered) {
      ctx.fillStyle = '#333';
    } else {
      // Darker for heavier weight
      var shade = Math.round(30 + (1 - w) * 40);
      ctx.fillStyle = 'rgb(' + shade + ',' + shade + ',' + shade + ')';
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

    // Pinned indicator — small ring
    if (n._pinned) {
      ctx.beginPath();
      ctx.arc(n.x, n.y, drawR + 3, 0, Math.PI * 2);
      ctx.strokeStyle = 'rgba(0, 154, 250, 0.4)';
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
      ctx.strokeStyle = 'rgba(0, 0, 0, ' + alpha + ')';
      ctx.lineWidth = 1;
      ctx.stroke();

      // Tiny terminal bulb
      ctx.beginPath();
      ctx.arc(endX, endY, 1.5, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(0, 0, 0, ' + (alpha * 0.8) + ')';
      ctx.fill();
    }
  }

  function drawLabel(n, highlighted) {
    var label = n.label.length > 25 ? n.label.substring(0, 23) + '...' : n.label;
    ctx.font = (highlighted ? 'bold ' : '') + '12px "Times New Roman", Times, serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    ctx.fillStyle = highlighted ? '#009AFA' : '#444';
    ctx.fillText(label, n.x, n.y + n.r + 16);
  }

  // ── Detail panel ───────────────────────────────────────────────
  function showDetail(d) {
    currentClusterId = d.id;
    detailLabel.textContent = d.label;
    detailDesc.textContent = d.description || '';
    detailCount.textContent = d.size + ' записей';
    detailWeight.textContent = 'вес: ' + Math.round(d.weight * 100) + '%';

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
              analyzeStatus.textContent = 'Готово. Найдено тем: ' + s.clusters_found;
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
      simulation.alpha(0.3).restart();
    }
  });

  // ── Init ───────────────────────────────────────────────────────
  loadGraph();
  fetch('/deep-mind/api/status')
    .then(function (r) { return r.json(); })
    .then(function (s) { if (s.running) pollStatus(); });
}());
