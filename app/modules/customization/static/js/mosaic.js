/**
 * Calendar mosaic renderer — paints the diary calendar's `.cube`
 * elements as windows into one or two images stretched across the
 * whole `.calendar-grid` bounding box.
 *
 * Runs on every page where customization is active, but immediately
 * exits if the page has no `.calendar-grid` (i.e. anywhere except the
 * mood-grid view). No-op when mosaic isn't configured.
 *
 * Loaded with `defer`, so DOMContentLoaded already happened.
 */
(function () {
  'use strict';

  var cfg = window.__CZ_MOSAIC__;
  if (!cfg || !cfg.filledUrl) return;

  var grid = document.querySelector('.calendar-grid');
  if (!grid) return;

  var cubes = grid.querySelectorAll('.cube');
  if (!cubes.length) return;

  var paint = function () {
    var gridRect = grid.getBoundingClientRect();
    var W = Math.max(1, Math.round(gridRect.width));
    var H = Math.max(1, Math.round(gridRect.height));

    // Pre-format the image / gradient / color values so we don't
    // recompute them per cube.
    var filledImg = 'url("' + cfg.filledUrl + '")';
    var emptyBg = null;
    if (cfg.emptyMode === 'image' || cfg.emptyMode === 'gradient') {
      emptyBg = cfg.emptyValue;  // already wrapped in url(...) or linear-gradient(...)
    }
    // Color mode: leave background-image unset so the existing CSS
    // var(--cube-empty-color, #fff) keeps working — that path supports
    // user customisation without a mosaic-specific color override.

    cubes.forEach(function (cube) {
      var r = cube.getBoundingClientRect();
      var x = Math.round(r.left - gridRect.left);
      var y = Math.round(r.top  - gridRect.top);
      var sizeStr = W + 'px ' + H + 'px';
      var posStr  = (-x) + 'px ' + (-y) + 'px';

      if (cube.classList.contains('filled')) {
        cube.style.backgroundImage = filledImg;
        cube.style.backgroundSize = sizeStr;
        cube.style.backgroundPosition = posStr;
        cube.style.backgroundRepeat = 'no-repeat';
      } else if (emptyBg) {
        cube.style.backgroundImage = emptyBg;
        cube.style.backgroundSize = sizeStr;
        cube.style.backgroundPosition = posStr;
        cube.style.backgroundRepeat = 'no-repeat';
      } else {
        // Color-mode empty days: clear any previously-set inline image
        // so toggling mosaic off-then-on doesn't leave stale slices.
        cube.style.backgroundImage = '';
        cube.style.backgroundSize = '';
        cube.style.backgroundPosition = '';
      }
    });
  };

  // Repaint on resize. Debounce so dragging the window edge isn't
  // expensive at 60Hz × 365 cubes.
  var resizeTimer = null;
  window.addEventListener('resize', function () {
    if (resizeTimer) clearTimeout(resizeTimer);
    resizeTimer = setTimeout(paint, 80);
  });

  // First paint. The image's natural dimensions don't matter — the
  // browser always stretches to background-size; we paint
  // synchronously without waiting for image load.
  paint();
}());
