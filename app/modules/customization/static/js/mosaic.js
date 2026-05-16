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
    // For image / gradient modes the value is already a CSS image
    // function — wrapped server-side. For color mode we just have a
    // hex/rgb string, which goes onto `background-color` instead.
    var emptyImage = null;
    var emptyColor = null;
    if (cfg.emptyMode === 'image' || cfg.emptyMode === 'gradient') {
      emptyImage = cfg.emptyValue;
    } else if (cfg.emptyMode === 'color' && cfg.emptyValue) {
      emptyColor = cfg.emptyValue;
    }

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
        cube.style.backgroundColor = '';
      } else if (emptyImage) {
        cube.style.backgroundImage = emptyImage;
        cube.style.backgroundSize = sizeStr;
        cube.style.backgroundPosition = posStr;
        cube.style.backgroundRepeat = 'no-repeat';
        cube.style.backgroundColor = '';
      } else if (emptyColor) {
        // Apply the mosaic-specific empty colour inline. We deliberately
        // override the existing `var(--cube-empty-color)` fallback so the
        // user's mosaic-empty-color picker actually drives empty cubes
        // when mosaic is on — without this, the value was saved but
        // never reached the DOM.
        cube.style.backgroundImage = '';
        cube.style.backgroundSize = '';
        cube.style.backgroundPosition = '';
        cube.style.backgroundColor = emptyColor;
      } else {
        // Color mode with no value set: defer to existing CSS.
        cube.style.backgroundImage = '';
        cube.style.backgroundSize = '';
        cube.style.backgroundPosition = '';
        cube.style.backgroundColor = '';
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
