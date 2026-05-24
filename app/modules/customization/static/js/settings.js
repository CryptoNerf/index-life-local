/**
 * Customization settings — live preview wiring.
 *
 * Architecture:
 *  - Each color picker has data-key="<css-var-name-without-leading-dashes>".
 *  - On change, the CSS variable is set on :root → the entire page
 *    (including the user's actual nav, footer, etc.) updates instantly.
 *  - JS-rendered previews (chart SVG, neural map canvas) read the
 *    current CSS values via getComputedStyle and redraw.
 *  - Saving is one POST with the full snapshot of changed values.
 *
 * No frameworks; uses d3 (already bundled with deep_mind) only for the
 * neural map mini-preview, with a graceful fallback if d3 isn't loaded.
 */
(function () {
  'use strict';

  var ROOT = document.documentElement;
  var savedMsg = document.getElementById('cz-saved-msg');
  var saveBtn  = document.getElementById('cz-save-btn');
  var resetBtn = document.getElementById('cz-reset-btn');

  // Track all keys we manage on this page (read from the DOM so adding
  // a control in HTML is enough, no JS to update).
  var pickers = Array.prototype.slice.call(
    document.querySelectorAll('input.cz-color[data-key]')
  );
  // Sliders (range inputs) for bg-image-blur, bg-image-opacity,
  // bg-gradient-angle. data-unit tells us how to convert slider value
  // to a CSS-ready string ('px', 'deg', or 'percent' which we map to
  // 0..1 for opacity).
  var sliders = Array.prototype.slice.call(
    document.querySelectorAll('input.cz-slider[data-key]')
  );
  // Select dropdowns (fonts).
  var selects = Array.prototype.slice.call(
    document.querySelectorAll('select.cz-select[data-key]')
  );
  // Hidden fields (bg-type, bg-image-filename, custom-font-filename).
  var hiddens = Array.prototype.slice.call(
    document.querySelectorAll('input[type="hidden"][data-key]')
  );
  // Boolean toggles (currently: notes-use-body-font). Stored as
  // 'true'/'false' string so the validator stays simple.
  var toggles = Array.prototype.slice.call(
    document.querySelectorAll('input.cz-toggle[data-key]')
  );

  // Lookup table: id → CSS family (mirrors the server-side catalog,
  // populated lazily via /customization/api/fonts on page load).
  var FONT_FAMILY_BY_ID = Object.create(null);
  var customFontFilename = (document.getElementById('cz-custom-font-filename') || {}).value || '';

  // Track which keys have been changed since last save — only those go
  // to the server, plus they're what we send back on Reset.
  var dirtyKeys = {};

  // ── CSS var helpers ──────────────────────────────────────────
  function applyVar(key, value) {
    ROOT.style.setProperty('--' + key, value);
  }
  function readVar(key) {
    return getComputedStyle(ROOT).getPropertyValue('--' + key).trim();
  }

  // ── Hex utilities ────────────────────────────────────────────
  function isHexColor(s) {
    return /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.test(s);
  }
  function normalizeHex(s) {
    if (!s) return s;
    var v = s.trim().toLowerCase();
    if (!v.startsWith('#')) v = '#' + v;
    if (/^#[0-9a-f]{3}$/.test(v)) {
      // expand short form so the picker accepts it
      v = '#' + v[1] + v[1] + v[2] + v[2] + v[3] + v[3];
    }
    return v;
  }

  // ── Wire up every picker + its hex twin ──────────────────────
  pickers.forEach(function (picker) {
    var key = picker.getAttribute('data-key');
    var hex = document.querySelector('input[data-hex-for="' + picker.id + '"]');

    picker.addEventListener('input', function () {
      var v = picker.value;
      if (hex) hex.value = v;
      applyVar(key, v);
      dirtyKeys[key] = true;
      onPreviewChange(key);
    });

    if (hex) {
      hex.addEventListener('input', function () {
        var v = normalizeHex(hex.value);
        if (!isHexColor(v)) return;  // ignore invalid mid-typing
        picker.value = v;
        applyVar(key, v);
        dirtyKeys[key] = true;
        onPreviewChange(key);
      });
      hex.addEventListener('blur', function () {
        // Snap back to picker value if blur left an invalid string
        if (!isHexColor(normalizeHex(hex.value))) {
          hex.value = picker.value;
        }
      });
    }
  });

  // ── Sliders ───────────────────────────────────────────────────
  // Each slider has data-unit telling us how to format the value.
  // Display is a sibling span '#<id>-val'.
  sliders.forEach(function (slider) {
    var key = slider.getAttribute('data-key');
    var unit = slider.getAttribute('data-unit');
    var label = document.getElementById(slider.id + '-val');

    function format(rawVal) {
      if (unit === 'percent') return rawVal + '%';
      return rawVal + unit;
    }
    function toCssValue(rawVal) {
      if (unit === 'percent') return (parseInt(rawVal, 10) / 100).toString();
      return rawVal + unit;
    }

    slider.addEventListener('input', function () {
      var raw = slider.value;
      if (label) label.textContent = format(raw);
      applyVar(key, toCssValue(raw));
      dirtyKeys[key] = true;
      onPreviewChange(key);
    });
  });

  // ── Font selectors ──────────────────────────────────────────
  // Apply the chosen family as the live --font-* CSS variable. The
  // 'times' id resolves to no override (CSS fallback wins), 'custom'
  // resolves to the 'Custom' face which only exists if a font was
  // uploaded.
  selects.forEach(function (sel) {
    var key = sel.getAttribute('data-key');
    sel.addEventListener('change', function () {
      var id = sel.value;
      var family = resolveFontFamily(id);
      // CSS variable name mirrors data-key minus '-id' suffix.
      var cssVarName = key.replace('-id', '');
      if (family) {
        applyVar(cssVarName, family);
      } else {
        // Reset to fallback by clearing the var
        document.documentElement.style.removeProperty('--' + cssVarName);
      }
      dirtyKeys[key] = true;
    });
  });

  function resolveFontFamily(id) {
    if (!id || id === 'times') return null;  // null = clear var, use CSS fallback
    if (id === 'custom') {
      return customFontFilename ? "'Custom', sans-serif" : null;
    }
    return FONT_FAMILY_BY_ID[id] || null;
  }

  // Pull catalog so we know id → family mapping for live preview.
  fetch('/customization/api/fonts')
    .then(function (r) { return r.json(); })
    .then(function (data) {
      (data.fonts || []).forEach(function (f) {
        FONT_FAMILY_BY_ID[f.id] = f.family;
      });
    });

  // ── Boolean toggles ────────────────────────────────────────
  toggles.forEach(function (cb) {
    var key = cb.getAttribute('data-key');
    cb.addEventListener('change', function () {
      var v = cb.checked ? 'true' : 'false';
      dirtyKeys[key] = true;
      // Side effects per key
      if (key === 'notes-use-body-font') {
        applyNotesFont(v === 'true');
      }
      if (key === 'auto-invert-text') {
        applyAutoInvert();
      }
    });
  });

  // ── Auto-invert text (Stage 7) ───────────────────────────────
  // Mirrors context_processor._auto_invert_overrides so live preview
  // matches what the next page render will produce. When the toggle is
  // off, we clear any computed override so the manual text-color picker
  // takes over again.
  function effectiveBgRgb() {
    var bgType = (document.getElementById('cz-bg-type') || {}).value || 'color';
    if (bgType === 'color') {
      var c = (document.getElementById('cz-bg-color') || {}).value || '#ffffff';
      return hexToRgb(c);
    }
    if (bgType === 'gradient') {
      var f = (document.getElementById('cz-grad-from') || {}).value || '#ffffff';
      var t = (document.getElementById('cz-grad-to')   || {}).value || '#dddddd';
      var a = hexToRgb(f), b = hexToRgb(t);
      return [
        Math.round((a[0] + b[0]) / 2),
        Math.round((a[1] + b[1]) / 2),
        Math.round((a[2] + b[2]) / 2),
      ];
    }
    return null;  // image: can't compute without sampling
  }
  function luma(rgb) {
    return rgb[0] * 0.299 + rgb[1] * 0.587 + rgb[2] * 0.114;
  }
  function applyAutoInvert() {
    var toggle = document.getElementById('cz-auto-invert');
    var on = toggle && toggle.checked;
    if (!on) {
      // Restore manual values. The pickers carry the current intent.
      var tc = (document.getElementById('cz-text-color') || {}).value;
      var tm = (document.getElementById('cz-text-muted') || {}).value;
      if (tc) applyVar('text-color', tc);
      if (tm) applyVar('text-muted', tm);
      return;
    }
    var rgb = effectiveBgRgb();
    if (!rgb) return;  // image bg, no overlay — leave whatever's set
    if (luma(rgb) < 128) {
      applyVar('text-color', '#ffffff');
      applyVar('text-muted', '#cccccc');
    } else {
      applyVar('text-color', '#000000');
      applyVar('text-muted', '#666666');
    }
  }

  function applyNotesFont(on) {
    if (on) {
      // Mirror body font (computed from current selector). If the
      // current --font-body is unset (Times default), we still emit
      // an explicit Times stack so the live preview on this page
      // shows the toggle had an effect when body=Times.
      var bodyVar = readVar('font-body');
      applyVar('font-notes', bodyVar || "'Times New Roman', Times, serif");
    } else {
      document.documentElement.style.removeProperty('--font-notes');
    }
  }

  // Re-apply notes font whenever body font changes (so toggle remains
  // consistent when user switches body font with toggle on).
  selects.forEach(function (sel) {
    if (sel.getAttribute('data-key') === 'font-body-id') {
      sel.addEventListener('change', function () {
        var notesToggle = document.getElementById('cz-notes-use-body');
        if (notesToggle && notesToggle.checked) {
          applyNotesFont(true);
        }
      });
    }
  });

  // ── Custom font upload ──────────────────────────────────────
  var fontUploadTrigger = document.getElementById('cz-font-upload-trigger');
  var fontUploadInput   = document.getElementById('cz-font-upload-input');
  var fontFilenameField = document.getElementById('cz-custom-font-filename');
  var currentFontField  = document.getElementById('cz-current-font');
  var fontClearBtn      = document.getElementById('cz-font-clear');

  if (fontUploadTrigger && fontUploadInput) {
    fontUploadTrigger.addEventListener('click', function () { fontUploadInput.click(); });
    fontUploadInput.addEventListener('change', function () {
      var file = fontUploadInput.files && fontUploadInput.files[0];
      if (!file) return;
      if (file.size > 5 * 1024 * 1024) {
        alert('Font file too large (max 5 MB).');
        return;
      }
      fontUploadTrigger.disabled = true;
      fontUploadTrigger.textContent = 'Uploading…';
      var fd = new FormData();
      fd.append('file', file);
      fetch('/customization/api/upload-font', { method: 'POST', body: fd })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          fontUploadTrigger.disabled = false;
          fontUploadTrigger.textContent = 'Upload…';
          if (data.error) {
            alert('Upload failed: ' + data.error);
            return;
          }
          customFontFilename = data.filename;
          if (fontFilenameField) fontFilenameField.value = data.filename;
          if (currentFontField) currentFontField.textContent = data.filename.substr(0, 8) + '…';
          if (fontClearBtn) fontClearBtn.disabled = false;
          dirtyKeys['custom-font-filename'] = true;

          // Inject @font-face for the new file so 'Custom' works in the
          // live preview without a page reload.
          injectCustomFontFace(data.filename);
        })
        .catch(function (err) {
          fontUploadTrigger.disabled = false;
          fontUploadTrigger.textContent = 'Upload…';
          alert('Upload failed: ' + err);
        });
    });
  }

  if (fontClearBtn) {
    fontClearBtn.addEventListener('click', function () {
      customFontFilename = '';
      if (fontFilenameField) fontFilenameField.value = '';
      if (currentFontField) currentFontField.textContent = 'no custom font uploaded';
      fontClearBtn.disabled = true;
      dirtyKeys['custom-font-filename'] = true;
      removeCustomFontFace();
      // If any selector was 'custom', fall back to default
      selects.forEach(function (sel) {
        if (sel.value === 'custom') {
          sel.value = 'times';
          var key = sel.getAttribute('data-key');
          var cssVarName = key.replace('-id', '');
          document.documentElement.style.removeProperty('--' + cssVarName);
          dirtyKeys[key] = true;
        }
      });
    });
  }

  function injectCustomFontFace(filename) {
    var existing = document.getElementById('cz-custom-font-face');
    if (existing) existing.remove();
    var s = document.createElement('style');
    s.id = 'cz-custom-font-face';
    s.textContent =
      '@font-face { font-family: "Custom"; font-style: normal;' +
      ' font-weight: normal; font-display: swap;' +
      ' src: url("/customization/uploads/' + filename + '"); }';
    document.head.appendChild(s);
  }
  function removeCustomFontFace() {
    var existing = document.getElementById('cz-custom-font-face');
    if (existing) existing.remove();
  }
  // If a custom font is already saved, inject its @font-face on load
  // so 'Custom' is usable in selectors immediately.
  if (customFontFilename) injectCustomFontFace(customFontFilename);

  // If notes-use-body-font is already on (saved value), the
  // context_processor has already emitted --font-notes — but selecting a
  // different body font in the live preview wouldn't update --font-notes
  // unless we re-apply on every body-font change. Initial sync: noop;
  // subsequent body-font changes are handled by the listener above.

  // ── Background type toggle (color / gradient / image) ────────
  var bgTypeBtns = Array.prototype.slice.call(
    document.querySelectorAll('.cz-bg-type-btn')
  );
  var bgTypeHidden = document.getElementById('cz-bg-type');

  function setBgType(type) {
    bgTypeBtns.forEach(function (b) {
      b.classList.toggle('active', b.getAttribute('data-type') === type);
    });
    document.querySelectorAll('.cz-bg-pane').forEach(function (p) {
      p.classList.toggle('cz-pane-active', p.getAttribute('data-pane') === type);
    });
    if (bgTypeHidden) {
      bgTypeHidden.value = type;
      dirtyKeys['bg-type'] = true;
    }
    rebuildBgImageVar();
  }

  bgTypeBtns.forEach(function (btn) {
    btn.addEventListener('click', function () {
      setBgType(btn.getAttribute('data-type'));
    });
  });

  // ── bg-image composition (mirrors server-side _compose_bg_image) ─
  function rebuildBgImageVar() {
    var type = bgTypeHidden ? bgTypeHidden.value : 'color';
    if (type === 'gradient') {
      var from = (document.getElementById('cz-grad-from') || {}).value || '#ffffff';
      var to   = (document.getElementById('cz-grad-to')   || {}).value || '#dddddd';
      var angSlider = document.getElementById('cz-grad-angle');
      var ang = angSlider ? angSlider.value + 'deg' : '180deg';
      applyVar('bg-image', 'linear-gradient(' + ang + ', ' + from + ', ' + to + ')');
    } else if (type === 'image') {
      var fnInput = document.getElementById('cz-bg-filename');
      var fn = fnInput ? fnInput.value : '';
      if (fn) {
        applyVar('bg-image', 'url("/customization/uploads/' + fn + '")');
      } else {
        applyVar('bg-image', 'none');
      }
    } else {
      applyVar('bg-image', 'none');
    }
  }

  // Whenever the gradient inputs change, rebuild the bg-image var
  ['cz-grad-from', 'cz-grad-to', 'cz-grad-angle'].forEach(function (id) {
    var el = document.getElementById(id);
    if (el) el.addEventListener('input', rebuildBgImageVar);
  });

  // ── File upload ──────────────────────────────────────────────
  var uploadTrigger = document.getElementById('cz-upload-trigger');
  var uploadInput   = document.getElementById('cz-upload-input');
  var bgFilename    = document.getElementById('cz-bg-filename');
  var currentFile   = document.getElementById('cz-current-file');
  var bgImageClear  = document.getElementById('cz-bg-image-clear');

  if (uploadTrigger && uploadInput) {
    uploadTrigger.addEventListener('click', function () { uploadInput.click(); });
    uploadInput.addEventListener('change', function () {
      var file = uploadInput.files && uploadInput.files[0];
      if (!file) return;
      if (file.size > 10 * 1024 * 1024) {
        alert('File too large (max 10 MB).');
        return;
      }
      uploadTrigger.disabled = true;
      uploadTrigger.textContent = 'Uploading…';
      var fd = new FormData();
      fd.append('file', file);
      fetch('/customization/api/upload-bg', { method: 'POST', body: fd })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          uploadTrigger.disabled = false;
          uploadTrigger.textContent = 'Choose…';
          if (data.error) {
            alert('Upload failed: ' + data.error);
            return;
          }
          if (bgFilename) bgFilename.value = data.filename;
          dirtyKeys['bg-image-filename'] = true;
          if (currentFile) currentFile.textContent = data.filename.substr(0, 8) + '…';
          if (bgImageClear) bgImageClear.disabled = false;
          // Auto-switch to image type so the upload is visible immediately
          setBgType('image');
          rebuildBgImageVar();
        })
        .catch(function (err) {
          uploadTrigger.disabled = false;
          uploadTrigger.textContent = 'Choose…';
          alert('Upload failed: ' + err);
        });
    });
  }

  if (bgImageClear) {
    bgImageClear.addEventListener('click', function () {
      if (bgFilename) bgFilename.value = '';
      dirtyKeys['bg-image-filename'] = true;
      if (currentFile) currentFile.textContent = 'no image uploaded';
      bgImageClear.disabled = true;
      setBgType('color');
      rebuildBgImageVar();
    });
  }

  // ── Save / Reset ─────────────────────────────────────────────
  function setSaved(visible) {
    if (visible) {
      savedMsg.classList.add('visible');
      setTimeout(function () { savedMsg.classList.remove('visible'); }, 2000);
    } else {
      savedMsg.classList.remove('visible');
    }
  }

  saveBtn.addEventListener('click', function () {
    saveBtn.disabled = true;
    var settings = {};
    // Collect from every input type that carries customization data.
    function collect(el) {
      var key = el.getAttribute('data-key');
      if (!key || !dirtyKeys[key]) return;
      var unit = el.getAttribute('data-unit');
      if (unit === 'percent') {
        // Slider value 0..100 → CSS unit interval 0..1
        settings[key] = (parseInt(el.value, 10) / 100).toString();
      } else if (unit) {
        settings[key] = el.value + unit;
      } else {
        settings[key] = el.value;
      }
    }
    pickers.forEach(collect);
    sliders.forEach(collect);
    selects.forEach(collect);
    hiddens.forEach(collect);
    toggles.forEach(function (cb) {
      var key = cb.getAttribute('data-key');
      if (key && dirtyKeys[key]) {
        settings[key] = cb.checked ? 'true' : 'false';
      }
    });

    if (Object.keys(settings).length === 0) {
      saveBtn.disabled = false;
      setSaved(true);
      return;
    }
    fetch('/customization/api/save', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ settings: settings }),
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        saveBtn.disabled = false;
        if (data.ok) {
          // Merge just-saved keys into SAVED_KEYS so `isAuthoritative()`
          // keeps returning true for them after Save (without a reload).
          // Without this, the picker value would stop being trusted as
          // soon as `dirtyKeys` is cleared below — leaving the preview
          // showing the global chart-color fallback while the real
          // page (next render) correctly uses the per-chart override.
          var justSaved = (data.saved || Object.keys(settings));
          for (var i = 0; i < justSaved.length; i++) {
            if (SAVED_KEYS.indexOf(justSaved[i]) === -1) {
              SAVED_KEYS.push(justSaved[i]);
            }
          }
          dirtyKeys = {};
          setSaved(true);
        } else {
          alert('Save failed: ' + (data.error || 'unknown'));
        }
      })
      .catch(function (err) {
        saveBtn.disabled = false;
        alert('Save failed: ' + err);
      });
  });

  // ── Storage cleanup (orphan upload sweeper) ─────────────────
  // Scan first, show count, only enable Delete after a scan so a
  // careless click doesn't nuke files without preview.
  var cleanupScan   = document.getElementById('cz-cleanup-scan');
  var cleanupRun    = document.getElementById('cz-cleanup-run');
  var cleanupOutput = document.getElementById('cz-cleanup-output');

  function fmtBytes(n) {
    if (n < 1024) return n + ' B';
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
    return (n / 1024 / 1024).toFixed(1) + ' MB';
  }

  if (cleanupScan && cleanupOutput && cleanupRun) {
    cleanupScan.addEventListener('click', function () {
      cleanupScan.disabled = true;
      cleanupOutput.textContent = 'Scanning…';
      fetch('/customization/api/orphan-uploads')
        .then(function (r) { return r.json(); })
        .then(function (data) {
          cleanupScan.disabled = false;
          var lines = [];
          if (!data.count) {
            lines.push('No orphan files. Nothing to clean up.');
            cleanupRun.disabled = true;
          } else {
            lines.push(data.count + ' orphan file(s), ' +
                       fmtBytes(data.total_bytes) + ' total:');
            data.orphans.forEach(function (o) {
              lines.push('  ' + o.filename + '  (' + fmtBytes(o.bytes) + ')');
            });
            cleanupRun.disabled = false;
          }
          cleanupOutput.textContent = lines.join('\n');
        })
        .catch(function (err) {
          cleanupScan.disabled = false;
          cleanupOutput.textContent = 'Scan failed: ' + err;
        });
    });

    cleanupRun.addEventListener('click', function () {
      if (!confirm('Permanently delete the listed orphan files?')) return;
      cleanupRun.disabled = true;
      cleanupRun.textContent = 'Deleting…';
      fetch('/customization/api/cleanup-orphans', { method: 'POST' })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          cleanupRun.textContent = 'Delete orphans';
          var lines = ['Deleted ' + data.deleted.length + ' file(s):'];
          data.deleted.forEach(function (n) { lines.push('  ' + n); });
          if (data.failed && data.failed.length) {
            lines.push('Failed:');
            data.failed.forEach(function (f) {
              lines.push('  ' + f.filename + ' — ' + f.error);
            });
          }
          cleanupOutput.textContent = lines.join('\n');
        })
        .catch(function (err) {
          cleanupRun.disabled = false;
          cleanupRun.textContent = 'Delete orphans';
          cleanupOutput.textContent = 'Cleanup failed: ' + err;
        });
    });
  }

  // ── Theme import (export is a plain GET via <a download>) ───
  // Importing replaces the entire theme — same effect as Reset
  // followed by Save with the new values. We hard-reload after to
  // resync controls. The server validates each key against the same
  // per-key validator as /api/save, so a malformed file can't smuggle
  // bad CSS in.
  var importTrigger = document.getElementById('cz-import-trigger');
  var importInput   = document.getElementById('cz-import-input');
  if (importTrigger && importInput) {
    importTrigger.addEventListener('click', function () { importInput.click(); });
    importInput.addEventListener('change', function () {
      var file = importInput.files && importInput.files[0];
      if (!file) return;
      if (!confirm(
            'Replace current theme with the file contents?\n' +
            'Your current settings will be overwritten.'
          )) {
        importInput.value = '';
        return;
      }
      var fd = new FormData();
      fd.append('file', file);
      importTrigger.disabled = true;
      importTrigger.textContent = 'Importing…';
      fetch('/customization/api/import', { method: 'POST', body: fd })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          importTrigger.disabled = false;
          importTrigger.textContent = 'Import';
          importInput.value = '';
          if (!data.ok) {
            alert('Import failed: ' + (data.error || 'unknown'));
            return;
          }
          var msg = 'Imported ' + (data.imported || []).length + ' settings';
          if ((data.rejected || []).length) {
            msg += ' (rejected: ' + data.rejected.join(', ') + ')';
          }
          alert(msg);
          window.location.reload();
        })
        .catch(function (err) {
          importTrigger.disabled = false;
          importTrigger.textContent = 'Import';
          alert('Import failed: ' + err);
        });
    });
  }

  // ── Per-section reset ────────────────────────────────────────
  // Each section has a small "reset section" button next to its title.
  // Clicking it clears just that section's keys server-side. To get
  // the UI back in sync without a complex per-section restore routine,
  // we hard-reload the page — same effect as the user pressing F5
  // after the server-side reset.
  Array.prototype.slice
    .call(document.querySelectorAll('.cz-section-reset'))
    .forEach(function (btn) {
      btn.addEventListener('click', function () {
        var section = btn.getAttribute('data-section');
        if (!confirm('Reset this section to defaults?')) return;
        btn.disabled = true;
        fetch('/customization/api/reset-section', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ section: section }),
        })
          .then(function (r) { return r.json(); })
          .then(function (data) {
            if (!data.ok) {
              alert('Reset failed: ' + (data.error || 'unknown'));
              btn.disabled = false;
              return;
            }
            // Hard reload so all controls reflect the reset values.
            window.location.reload();
          })
          .catch(function (err) {
            alert('Reset failed: ' + err);
            btn.disabled = false;
          });
      });
    });

  resetBtn.addEventListener('click', function () {
    if (!confirm('Reset all customization to defaults?')) return;
    resetBtn.disabled = true;
    fetch('/customization/api/reset', { method: 'POST' })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        resetBtn.disabled = false;
        if (!data.ok) return;

        // Apply color picker defaults
        pickers.forEach(function (picker) {
          var key = picker.getAttribute('data-key');
          var def = data.settings[key];
          if (!def) return;
          if (isHexColor(def)) {
            picker.value = def;
            var hex = document.querySelector('input[data-hex-for="' + picker.id + '"]');
            if (hex) hex.value = def;
          }
          applyVar(key, def);
        });

        // Apply slider defaults
        sliders.forEach(function (slider) {
          var key = slider.getAttribute('data-key');
          var unit = slider.getAttribute('data-unit');
          var def = data.settings[key];
          if (!def) return;
          var raw;
          if (unit === 'percent') {
            raw = Math.round(parseFloat(def) * 100);
          } else {
            raw = parseInt(String(def).replace(/[a-z%]/g, ''), 10) || 0;
          }
          slider.value = raw;
          var label = document.getElementById(slider.id + '-val');
          if (label) {
            label.textContent = unit === 'percent' ? raw + '%' : raw + unit;
          }
          applyVar(key, def);
        });

        // Reset selects (fonts) and clear computed font vars
        selects.forEach(function (sel) {
          var key = sel.getAttribute('data-key');
          sel.value = data.settings[key] || 'times';
          var cssVarName = key.replace('-id', '');
          document.documentElement.style.removeProperty('--' + cssVarName);
        });

        // Reset hidden fields + type toggle
        hiddens.forEach(function (h) {
          var key = h.getAttribute('data-key');
          h.value = data.settings[key] || '';
        });
        var bgType = data.settings['bg-type'] || 'color';
        setBgType(bgType);

        // Reset image upload UI
        if (currentFile) {
          var fn = data.settings['bg-image-filename'];
          currentFile.textContent = fn ? fn.substr(0, 8) + '…' : 'no image uploaded';
        }
        if (bgImageClear) bgImageClear.disabled = !data.settings['bg-image-filename'];

        // Reset toggles
        toggles.forEach(function (cb) {
          var key = cb.getAttribute('data-key');
          cb.checked = data.settings[key] === 'true';
          if (key === 'notes-use-body-font') {
            applyNotesFont(cb.checked);
          }
        });

        // Reset custom font UI
        customFontFilename = data.settings['custom-font-filename'] || '';
        if (currentFontField) {
          currentFontField.textContent = customFontFilename
            ? customFontFilename.substr(0, 8) + '…'
            : 'no custom font uploaded';
        }
        if (fontClearBtn) fontClearBtn.disabled = !customFontFilename;
        removeCustomFontFace();

        // Clear --bg-image (so the inactive state matches the freshly-reset look)
        rebuildBgImageVar();

        // Full reset wipes all previously-saved per-chart overrides;
        // SAVED_KEYS must drop them so `isAuthoritative()` correctly
        // cascades preview colours back through chart-color.
        SAVED_KEYS.length = 0;
        dirtyKeys = {};
        renderAll();
        setSaved(true);
      });
  });

  // ── Mini-calendar preview ────────────────────────────────────
  function renderCalendar() {
    var box = document.getElementById('preview-calendar');
    if (!box) return;
    box.innerHTML = '';
    // 3 months of fake days: 30 cubes each, randomly filled with a
    // deterministic pattern so the preview doesn't reshuffle on every
    // tick (visual noise on every keystroke would be distracting).
    for (var m = 0; m < 3; m++) {
      var month = document.createElement('div');
      month.className = 'preview-mini-month';
      for (var d = 0; d < 30; d++) {
        var cube = document.createElement('div');
        cube.className = 'preview-mini-cube';
        // Pseudo-random fill: ~60% in first month, 35% in second, 10% in third
        // — visualises a typical "more recent days are denser" pattern.
        var threshold = m === 0 ? 0.6 : m === 1 ? 0.35 : 0.1;
        // Stable hash for (m, d): no reshuffle on rerender
        var h = Math.sin(m * 31 + d * 7) * 1000;
        h = h - Math.floor(h);
        if (h < threshold) cube.classList.add('filled');
        // Mark last filled day in month 1 as "today"
        if (m === 1 && d === 14) cube.classList.add('today');
        month.appendChild(cube);
      }
      box.appendChild(month);
    }
  }

  // ── Per-chart mini previews ──────────────────────────────────
  // Each preview function renders an SVG mirror of its insights chart,
  // pulling values straight from the live picker inputs so the user
  // sees the effect without saving. Resolution helper:
  //
  // Per-chart keys (river-*, spiral-*, etc.) are AUTHORITATIVE only when:
  //   (a) the user touched the picker this session (`dirtyKeys`), OR
  //   (b) the value was saved server-side (`__CZ_SAVED_KEYS__`)
  // Otherwise the picker is showing the schema default and the real
  // page would cascade up to `chart-color` — so we mirror that here by
  // ignoring the picker value and letting the caller's fallback win.
  var SAVED_KEYS = window.__CZ_SAVED_KEYS__ || [];
  function isAuthoritative(key) {
    return dirtyKeys[key] === true || SAVED_KEYS.indexOf(key) !== -1;
  }
  function readPicker(el) {
    if (el.classList.contains('cz-color')) return el.value;
    if (el.classList.contains('cz-slider')) {
      var unit = el.getAttribute('data-unit');
      if (unit === 'percent') return (parseInt(el.value, 10) / 100).toString();
      return el.value + (unit || '');
    }
    return null;
  }
  function getKey(key, fallback) {
    var el = document.querySelector('[data-key="' + key + '"]');
    if (el && isAuthoritative(key)) {
      var v = readPicker(el);
      if (v !== null) return v;
    }
    var cssVar = readVar(key);
    if (cssVar) return cssVar;
    // No authoritative source — fall back to whatever the caller said.
    return fallback;
  }
  function getColor(key, fallback) {
    return getKey(key, fallback) || fallback;
  }
  function getNum(key, fallback) {
    var v = getKey(key, '');
    var n = parseFloat(v);
    return isNaN(n) ? fallback : n;
  }
  function svgEl(svg, tag, attrs) {
    var n = document.createElementNS('http://www.w3.org/2000/svg', tag);
    for (var k in attrs) {
      if (attrs.hasOwnProperty(k)) n.setAttribute(k, attrs[k]);
    }
    svg.appendChild(n);
    return n;
  }
  function clear(svg) { while (svg.firstChild) svg.removeChild(svg.firstChild); }

  function hexToRgb(hex) {
    if (!hex || hex[0] !== '#') return [0, 0, 0];
    var s = hex.slice(1);
    if (s.length === 3) {
      return [parseInt(s[0] + s[0], 16),
              parseInt(s[1] + s[1], 16),
              parseInt(s[2] + s[2], 16)];
    }
    if (s.length === 6) {
      return [parseInt(s.slice(0, 2), 16),
              parseInt(s.slice(2, 4), 16),
              parseInt(s.slice(4, 6), 16)];
    }
    return [0, 0, 0];
  }
  function rgba(hex, opacity) {
    var rgb = hexToRgb(hex);
    return 'rgba(' + rgb.join(',') + ',' + opacity + ')';
  }

  // ── River: smoothed line + area + raw dots + today vertical ──
  function renderRiver(svg) {
    clear(svg);
    var W = 240, H = 140, pad = 12;
    var data = [6, 7, 5, 8, 6, 7, 4, 6, 8, 7, 9, 6];
    var stepX = (W - pad * 2) / (data.length - 1);
    var pts = data.map(function (v, i) {
      return [pad + i * stepX, H - pad - ((v - 1) / 9) * (H - pad * 2)];
    });

    // Per-chart picker values are only authoritative when dirty/saved
    // (see getKey). For untouched keys, fall back along the same chain
    // the server uses: chart-color global → CSS default. river-area
    // falls back to '#000' (not lineColor) because the server emits
    // rgba(0,0,0,opacity) when only opacity is set, not rgba(lineColor).
    var chartColor  = getColor('chart-color', '#000');
    var lineColor   = getColor('river-line-color',  chartColor);
    var lineWidth   = getNum('river-line-width', 1.6);
    var areaColor   = getColor('river-area-color',  '#000000');
    var areaOpacity = getNum('river-area-opacity', 0.08);
    var dotColor    = getColor('river-dot-color',   chartColor);
    var todayColor  = getColor('river-today-color', getColor('brand-color', '#009afa'));
    var gridColor   = getColor('river-grid-color',  getColor('chart-grid-color', '#c8c8c8'));

    // Gridlines (3 dashed horizontals at 4, 6, 8)
    [4, 6, 8].forEach(function (v) {
      var y = H - pad - ((v - 1) / 9) * (H - pad * 2);
      svgEl(svg, 'line', {
        x1: pad, y1: y, x2: W - pad, y2: y,
        stroke: gridColor, 'stroke-width': 1, 'stroke-dasharray': '2 4',
      });
    });
    // Area
    var areaPts = pts.slice();
    areaPts.unshift([pts[0][0], H - pad]);
    areaPts.push([pts[pts.length - 1][0], H - pad]);
    svgEl(svg, 'polygon', {
      points: areaPts.map(function (p) { return p.join(','); }).join(' '),
      fill: rgba(areaColor, areaOpacity),
      stroke: 'none',
    });
    // Today marker (last point)
    svgEl(svg, 'line', {
      x1: pts[pts.length - 1][0], y1: pad,
      x2: pts[pts.length - 1][0], y2: H - pad,
      stroke: todayColor, 'stroke-width': 1.4, 'stroke-dasharray': '3 3',
    });
    // Smoothed-ish line
    svgEl(svg, 'polyline', {
      points: pts.map(function (p) { return p.join(','); }).join(' '),
      fill: 'none', stroke: lineColor,
      'stroke-width': lineWidth,
      'stroke-linejoin': 'round', 'stroke-linecap': 'round',
    });
    // Raw daily dots
    pts.forEach(function (p) {
      svgEl(svg, 'circle', { cx: p[0], cy: p[1], r: 2.5, fill: dotColor, opacity: 0.55 });
    });
  }

  // ── Spiral: dots on Archimedean spiral + guide rings + today ──
  function renderSpiral(svg) {
    clear(svg);
    var W = 240, H = 140, cx = W / 2, cy = H / 2;
    var dotColor   = getColor('spiral-dot-color',   getColor('chart-color', '#000'));
    var guideColor = getColor('spiral-guide-color', getColor('chart-grid-color', '#d8d8d8'));
    var todayColor = getColor('spiral-today-color', getColor('brand-color', '#009afa'));
    var monthColor = getColor('spiral-month-color', '#666');

    // Guide concentric circles
    [16, 32, 50].forEach(function (r) {
      svgEl(svg, 'circle', { cx: cx, cy: cy, r: r,
        fill: 'none', stroke: guideColor, 'stroke-width': 1 });
    });
    // Month markers (12 ticks at outer ring)
    for (var m = 0; m < 12; m++) {
      var ang = (m / 12) * Math.PI * 2 - Math.PI / 2;
      svgEl(svg, 'circle', {
        cx: cx + Math.cos(ang) * 56, cy: cy + Math.sin(ang) * 56,
        r: 1.5, fill: monthColor,
      });
    }
    // Spiral data dots
    var N = 60;
    for (var i = 0; i < N; i++) {
      var t = i / N;
      var r = 8 + t * 44;
      var a = t * Math.PI * 6 - Math.PI / 2;
      var op = 0.25 + (Math.sin(i * 0.7) * 0.5 + 0.5) * 0.65;
      svgEl(svg, 'circle', {
        cx: cx + Math.cos(a) * r, cy: cy + Math.sin(a) * r,
        r: 2.4, fill: dotColor, 'fill-opacity': op,
      });
    }
    // Today ring
    svgEl(svg, 'circle', {
      cx: cx + Math.cos(Math.PI * 5.7) * 50,
      cy: cy + Math.sin(Math.PI * 5.7) * 50,
      r: 5, fill: 'none', stroke: todayColor, 'stroke-width': 1.6,
    });
  }

  // ── Rhythm: 7×12 heatmap with weekend separator ────────────
  function renderRhythm(svg) {
    clear(svg);
    var W = 240, H = 140, padL = 14, padT = 8;
    var cols = 12, rows = 7;
    var cellW = (W - padL - 6) / cols;
    var cellH = (H - padT - 8) / rows;

    var cellColor   = getColor('rhythm-cell-color',    getColor('chart-color', '#000'));
    var emptyColor  = getColor('rhythm-empty-color',   '#f0f0f0');
    var weekendCol  = getColor('rhythm-weekend-color', '#cccccc');

    // Pseudo-random opacities (deterministic so it doesn't reshuffle)
    for (var r = 0; r < rows; r++) {
      for (var c = 0; c < cols; c++) {
        var seed = Math.sin(r * 11 + c * 17) * 1000;
        var op = (seed - Math.floor(seed));
        var isEmpty = op < 0.12;
        svgEl(svg, 'rect', {
          x: padL + c * cellW, y: padT + r * cellH,
          width: cellW - 1, height: cellH - 1,
          fill: isEmpty ? emptyColor : cellColor,
          'fill-opacity': isEmpty ? 1 : (0.18 + op * 0.7),
        });
      }
    }
    // Weekend separator between Fri (row 4) and Sat (row 5)
    svgEl(svg, 'line', {
      x1: padL, y1: padT + 5 * cellH,
      x2: W - 6, y2: padT + 5 * cellH,
      stroke: weekendCol, 'stroke-width': 1.5, 'stroke-dasharray': '3 3',
    });
  }

  // ── Rose: 7 petals (weekdays) ──────────────────────────────
  function renderRose(svg) {
    clear(svg);
    var W = 240, H = 140, cx = W / 2, cy = H / 2;
    var petalColor = getColor('rose-petal-color',  getColor('chart-color', '#000'));
    var emptyColor = getColor('rose-empty-color',  '#eaeaea');
    var refColor   = getColor('rose-ref-color',    getColor('chart-grid-color', '#d8d8d8'));

    // 3 reference circles
    [20, 38, 56].forEach(function (r) {
      svgEl(svg, 'circle', { cx: cx, cy: cy, r: r,
        fill: 'none', stroke: refColor, 'stroke-width': 0.8 });
    });

    // 7 petals (sized by pseudo-random data)
    var sizes = [0.8, 0.6, 0.4, 0.9, 0.5, 0.7, 0.3];
    for (var i = 0; i < 7; i++) {
      var ang = (i / 7) * Math.PI * 2 - Math.PI / 2;
      var len = 20 + sizes[i] * 36;
      var w = 14;
      var ax = cx + Math.cos(ang) * len;
      var ay = cy + Math.sin(ang) * len;
      var px = -Math.sin(ang) * w;
      var py =  Math.cos(ang) * w;
      var p1 = (cx + px) + ',' + (cy + py);
      var p2 = ax + ',' + ay;
      var p3 = (cx - px) + ',' + (cy - py);
      var isEmpty = sizes[i] < 0.35;
      svgEl(svg, 'polygon', {
        points: cx + ',' + cy + ' ' + p1 + ' ' + p2 + ' ' + p3,
        fill: isEmpty ? emptyColor : petalColor,
        'fill-opacity': isEmpty ? 1 : 0.22 + sizes[i] * 0.6,
      });
    }
  }

  // ── Ridgeline: 6 stacked ridges ────────────────────────────
  function renderRidgeline(svg) {
    clear(svg);
    var W = 240, H = 140, padL = 14, padR = 6, padT = 6;
    var rows = 6;
    var rowH = (H - padT - 6) / rows;

    // ridge-fill-color defaults to '#000000' on the server (see
    // _composed_fill); ridge-line-color falls through chart-color, NOT
    // fillColor — the real chart emits .ridge-line { stroke: var(--chart-color) }.
    var fillColor    = getColor('ridge-fill-color',    '#000000');
    var fillOpacity  = getNum('ridge-fill-opacity', 0.20);
    var lineColor    = getColor('ridge-line-color',    getColor('chart-color', '#000'));
    var baseColor    = getColor('ridge-baseline-color', '#888');

    for (var r = 0; r < rows; r++) {
      var baseY = padT + (r + 1) * rowH;
      // Generate a "ridge" curve — sine + offset per row
      var pts = [];
      for (var i = 0; i <= 30; i++) {
        var x = padL + (i / 30) * (W - padL - padR);
        var t = i / 30;
        var y = baseY - (Math.sin(t * Math.PI * 2 + r * 0.7) * 0.5 + 0.5) * rowH * 0.7
                      - Math.sin(t * Math.PI * 4 + r) * 4;
        pts.push([x, y]);
      }
      // Filled area
      var pgPts = pts.slice();
      pgPts.unshift([padL, baseY]);
      pgPts.push([W - padR, baseY]);
      svgEl(svg, 'polygon', {
        points: pgPts.map(function (p) { return p.join(','); }).join(' '),
        fill: rgba(fillColor, fillOpacity), stroke: 'none',
      });
      // Outline
      svgEl(svg, 'polyline', {
        points: pts.map(function (p) { return p.join(','); }).join(' '),
        fill: 'none', stroke: lineColor, 'stroke-width': 1,
      });
      // Baseline
      svgEl(svg, 'line', {
        x1: padL, y1: baseY, x2: W - padR, y2: baseY,
        stroke: baseColor, 'stroke-width': 0.6, opacity: 0.6,
      });
    }
  }

  // ── Overview: heatmap + sidebar bars ───────────────────────
  function renderOverview(svg) {
    clear(svg);
    var W = 240, H = 140;
    var heatColor  = getColor('overview-heat-color',  getColor('chart-color', '#000'));
    // overview-empty-color falls back through cube-empty-color (real CSS:
    // .heat-empty { fill: var(--cube-empty-color, #fff); }).
    var emptyColor = getColor('overview-empty-color', getColor('cube-empty-color', '#fff'));
    var barColor   = getColor('overview-bar-color',   getColor('chart-color', '#000'));
    var todayColor = getColor('overview-today-color', getColor('brand-color', '#009afa'));
    var gridColor  = getColor('chart-grid-color',     '#d8d8d8');

    // Heatmap area (left 65%)
    var hW = 145, hH = H - 16;
    var cols = 26, rows = 7;
    var cw = hW / cols, ch = hH / rows;
    for (var r = 0; r < rows; r++) {
      for (var c = 0; c < cols; c++) {
        var seed = Math.sin(r * 13 + c * 7) * 1000;
        var op = seed - Math.floor(seed);
        if (op < 0.18) {
          svgEl(svg, 'rect', {
            x: 8 + c * cw, y: 8 + r * ch, width: cw - 0.5, height: ch - 0.5,
            fill: emptyColor, stroke: gridColor, 'stroke-width': 0.5,
          });
        } else {
          svgEl(svg, 'rect', {
            x: 8 + c * cw, y: 8 + r * ch, width: cw - 0.5, height: ch - 0.5,
            fill: heatColor, 'fill-opacity': 0.15 + op * 0.7,
          });
        }
      }
    }
    // Today highlight (one cell)
    svgEl(svg, 'rect', {
      x: 8 + 22 * cw, y: 8 + 4 * ch, width: cw - 0.5, height: ch - 0.5,
      fill: 'none', stroke: todayColor, 'stroke-width': 1.5,
    });
    // Bar chart (right 30%)
    var bX = 165, bY = 14, bW = 65, bH = H - 28;
    var bars = [0.4, 0.6, 0.55, 0.7, 0.5, 0.85, 0.45, 0.6, 0.7, 0.5, 0.65, 0.35];
    var step = bH / bars.length;
    bars.forEach(function (v, i) {
      svgEl(svg, 'rect', {
        x: bX, y: bY + i * step + 1,
        width: v * bW, height: step - 2,
        fill: barColor,
      });
    });
  }

  // ── Activities zoom: packed circles with two depth levels ───
  // Mirrors the production chart's pack-layout look: a few big "activity"
  // circles, each containing a couple of smaller "mention" circles.
  // Opacity within each group encodes data (mood delta / day rating) the
  // same way as the live page does.
  function renderActivitiesZoom(svg) {
    clear(svg);
    var W = 240, H = 140;
    var circleColor = getColor('az-circle-color',  getColor('chart-color', '#000'));
    var strokeColor = getColor('az-circle-stroke', '#4d4d4d');
    var canvasBg    = getColor('az-canvas-bg',     '#fafafa');
    var labelColor  = getColor('az-label-color',   '#ffffff');

    // Canvas background panel
    svgEl(svg, 'rect', { x: 0, y: 0, width: W, height: H,
      fill: canvasBg, stroke: '#eee' });

    // 3 activity circles with mention children — fixed deterministic
    // layout so the preview doesn't reshuffle on every keystroke.
    var activities = [
      {cx: 60,  cy: 70, r: 38, op: 0.65, label: 'walk',
       mentions: [{dx: -10, dy:  -6, r: 12, op: 0.55},
                  {dx:  12, dy:   8, r: 10, op: 0.40}]},
      {cx: 145, cy: 55, r: 30, op: 0.45, label: 'sport',
       mentions: [{dx:  -8, dy:   0, r:  9, op: 0.70}]},
      {cx: 195, cy: 95, r: 24, op: 0.35, label: 'food',
       mentions: [{dx:  -4, dy:  -4, r:  7, op: 0.50},
                  {dx:   6, dy:   5, r:  6, op: 0.30}]},
    ];

    activities.forEach(function (a) {
      svgEl(svg, 'circle', {
        cx: a.cx, cy: a.cy, r: a.r,
        fill: circleColor, 'fill-opacity': a.op,
        stroke: strokeColor, 'stroke-width': 0.6,
      });
      a.mentions.forEach(function (m) {
        svgEl(svg, 'circle', {
          cx: a.cx + m.dx, cy: a.cy + m.dy, r: m.r,
          fill: circleColor, 'fill-opacity': m.op,
          stroke: strokeColor, 'stroke-width': 0.4,
        });
      });
      var lbl = svgEl(svg, 'text', {
        x: a.cx, y: a.cy,
        'text-anchor': 'middle', 'dominant-baseline': 'central',
        'font-size': Math.max(8, a.r * 0.32), fill: labelColor,
        'font-family': readVar('font-body') || "'Times New Roman', Times, serif",
      });
      lbl.textContent = a.label;
    });
  }

  var CHART_RENDERERS = {
    'river':           renderRiver,
    'spiral':          renderSpiral,
    'rhythm':          renderRhythm,
    'rose':            renderRose,
    'ridgeline':       renderRidgeline,
    'overview':        renderOverview,
    'activities-zoom': renderActivitiesZoom,
  };

  function renderAllCharts() {
    document.querySelectorAll('[data-chart]').forEach(function (svg) {
      var renderer = CHART_RENDERERS[svg.getAttribute('data-chart')];
      if (renderer) renderer(svg);
    });
  }

  // ── Mini neural-map preview (Canvas) ─────────────────────────
  // Tiny static layout — no force simulation needed for a 6-node demo.
  // Click any node to mark it active (so the active-color picker has
  // a visible effect immediately).
  var neuralActiveIdx = 1;  // initial active node
  var neuralNodes = [
    { x: 0.30, y: 0.30, r: 22, label: 'work' },
    { x: 0.70, y: 0.28, r: 26, label: 'family' },
    { x: 0.20, y: 0.65, r: 18, label: 'sport' },
    { x: 0.55, y: 0.55, r: 24, label: 'travel' },
    { x: 0.82, y: 0.62, r: 20, label: 'reading' },
    { x: 0.45, y: 0.85, r: 18, label: 'food' },
  ];
  var neuralEdges = [
    [0, 1], [0, 3], [1, 3], [1, 4], [2, 5], [3, 5], [3, 4],
  ];

  function renderNeural() {
    var canvas = document.getElementById('preview-neural');
    if (!canvas) return;

    var dpr = window.devicePixelRatio || 1;
    var W = canvas.clientWidth;
    var H = canvas.clientHeight;
    canvas.width  = W * dpr;
    canvas.height = H * dpr;
    var ctx = canvas.getContext('2d');
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, W, H);

    var colNode   = readVar('neural-node-color')        || 'rgb(40,40,40)';
    var colActive = readVar('neural-node-active-color') || '#009afa';
    var colEdge   = readVar('neural-edge-color')        || 'rgba(0,0,0,0.25)';
    var colBg     = readVar('neural-canvas-bg')         || '#fafafa';

    // Paint the canvas background — clearRect leaves it transparent, so
    // without this fill the bg picker wouldn't visibly affect the preview.
    ctx.fillStyle = colBg;
    ctx.fillRect(0, 0, W, H);

    // Resolve fractional coords once
    var nodes = neuralNodes.map(function (n) {
      return { x: n.x * W, y: n.y * H, r: n.r, label: n.label };
    });

    // Edges first (under the nodes)
    ctx.strokeStyle = colEdge;
    ctx.lineWidth = 1.4;
    neuralEdges.forEach(function (e) {
      var a = nodes[e[0]], b = nodes[e[1]];
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.stroke();
    });

    // Nodes
    nodes.forEach(function (n, i) {
      var active = i === neuralActiveIdx;
      ctx.beginPath();
      ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2);
      ctx.fillStyle = active ? colActive : colNode;
      ctx.fill();

      // Label below
      ctx.fillStyle = readVar('text-color') || '#222';
      ctx.font = '11px ' + (readVar('font-body') || 'Times New Roman, serif');
      ctx.textAlign = 'center';
      ctx.textBaseline = 'top';
      ctx.fillText(n.label, n.x, n.y + n.r + 4);
    });
  }

  // Make the neural canvas clickable so the user can pick which node
  // is "active" — that's the only way to demo the active-color picker.
  (function bindNeuralClick() {
    var canvas = document.getElementById('preview-neural');
    if (!canvas) return;
    canvas.style.cursor = 'pointer';
    canvas.addEventListener('click', function (e) {
      var rect = canvas.getBoundingClientRect();
      var px = e.clientX - rect.left;
      var py = e.clientY - rect.top;
      for (var i = 0; i < neuralNodes.length; i++) {
        var n = neuralNodes[i];
        var nx = n.x * canvas.clientWidth;
        var ny = n.y * canvas.clientHeight;
        var dx = px - nx, dy = py - ny;
        if (dx * dx + dy * dy <= n.r * n.r) {
          neuralActiveIdx = i;
          renderNeural();
          return;
        }
      }
    });
  })();

  // ── Mosaic ─────────────────────────────────────────────────
  // Wires the mosaic UI: filled image upload, empty-mode toggle (color
  // / gradient / image), empty image upload. Renders a live mini-
  // calendar preview that uses the same per-cube background-position
  // technique as the production mosaic.js, so the user sees exactly
  // what will appear on the diary calendar.
  var mosaicFilledFilename = (document.getElementById('cz-mosaic-filled-filename') || {}).value || '';
  var mosaicEmptyFilename = (document.getElementById('cz-mosaic-empty-filename') || {}).value || '';
  var mosaicEmptyMode = (document.getElementById('cz-mosaic-empty-mode') || {}).value || 'color';

  function setMosaicEmptyMode(mode) {
    document.querySelectorAll('.cz-mosaic-empty-btn').forEach(function (b) {
      b.classList.toggle('active', b.getAttribute('data-mode') === mode);
    });
    document.querySelectorAll('.cz-mosaic-empty-pane').forEach(function (p) {
      p.classList.toggle('cz-pane-active', p.getAttribute('data-pane') === mode);
    });
    var hidden = document.getElementById('cz-mosaic-empty-mode');
    if (hidden) {
      hidden.value = mode;
      dirtyKeys['mosaic-empty-mode'] = true;
    }
    mosaicEmptyMode = mode;
    renderMosaicPreview();
  }

  document.querySelectorAll('.cz-mosaic-empty-btn').forEach(function (btn) {
    btn.addEventListener('click', function () {
      setMosaicEmptyMode(btn.getAttribute('data-mode'));
    });
  });

  function bindMosaicUpload(triggerId, inputId, clearId, currentId, hiddenId, dirtyKey, onSet) {
    var trigger = document.getElementById(triggerId);
    var input   = document.getElementById(inputId);
    var clear   = document.getElementById(clearId);
    var current = document.getElementById(currentId);
    var hidden  = document.getElementById(hiddenId);
    if (!trigger || !input) return;

    trigger.addEventListener('click', function () { input.click(); });
    input.addEventListener('change', function () {
      var file = input.files && input.files[0];
      if (!file) return;
      if (file.size > 10 * 1024 * 1024) {
        alert('File too large (max 10 MB).');
        return;
      }
      trigger.disabled = true;
      trigger.textContent = 'Uploading…';
      var fd = new FormData();
      fd.append('file', file);
      fetch('/customization/api/upload-bg', { method: 'POST', body: fd })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          trigger.disabled = false;
          trigger.textContent = 'Choose…';
          if (data.error) { alert('Upload failed: ' + data.error); return; }
          if (hidden) hidden.value = data.filename;
          if (current) current.textContent = data.filename.substr(0, 8) + '…';
          if (clear) clear.disabled = false;
          dirtyKeys[dirtyKey] = true;
          onSet(data.filename);
        });
    });
    if (clear) {
      clear.addEventListener('click', function () {
        if (hidden) hidden.value = '';
        if (current) current.textContent = 'no image uploaded';
        clear.disabled = true;
        dirtyKeys[dirtyKey] = true;
        onSet('');
      });
    }
  }

  bindMosaicUpload(
    'cz-mosaic-filled-trigger', 'cz-mosaic-filled-input',
    'cz-mosaic-filled-clear', 'cz-mosaic-filled-current',
    'cz-mosaic-filled-filename', 'mosaic-filled-filename',
    function (fn) {
      mosaicFilledFilename = fn;
      // Auto-enable mosaic when user uploads — convenience, otherwise
      // they have to remember to also flip the toggle.
      var enabled = document.getElementById('cz-mosaic-enabled');
      if (fn && enabled && !enabled.checked) {
        enabled.checked = true;
        dirtyKeys['mosaic-enabled'] = true;
      }
      renderMosaicPreview();
    });

  bindMosaicUpload(
    'cz-mosaic-empty-trigger', 'cz-mosaic-empty-input',
    'cz-mosaic-empty-clear', 'cz-mosaic-empty-current',
    'cz-mosaic-empty-filename', 'mosaic-empty-filename',
    function (fn) {
      mosaicEmptyFilename = fn;
      renderMosaicPreview();
    });

  // Re-render preview on every relevant change
  ['cz-mosaic-empty-color', 'cz-mosaic-empty-grad-from',
   'cz-mosaic-empty-grad-to', 'cz-mosaic-empty-grad-angle'].forEach(function (id) {
    var el = document.getElementById(id);
    if (el) el.addEventListener('input', renderMosaicPreview);
  });
  var enabledToggle = document.getElementById('cz-mosaic-enabled');
  if (enabledToggle) enabledToggle.addEventListener('change', renderMosaicPreview);

  function renderMosaicPreview() {
    var box = document.getElementById('preview-mosaic-calendar');
    if (!box) return;
    box.innerHTML = '';

    var fillFn = mosaicFilledFilename;
    var emptyFn = mosaicEmptyFilename;

    // Build 3 fake months × 30 cubes; same deterministic-fill pattern
    // as the existing color preview so it doesn't reshuffle on every
    // tick.
    var monthEls = [];
    for (var m = 0; m < 3; m++) {
      var month = document.createElement('div');
      month.className = 'preview-mini-month';
      monthEls.push(month);
      for (var d = 0; d < 30; d++) {
        var cube = document.createElement('div');
        cube.className = 'preview-mini-cube';
        var threshold = m === 0 ? 0.6 : m === 1 ? 0.35 : 0.1;
        var h = Math.sin(m * 31 + d * 7) * 1000;
        h = h - Math.floor(h);
        if (h < threshold) cube.classList.add('filled');
        if (m === 1 && d === 14) cube.classList.add('today');
        month.appendChild(cube);
      }
      box.appendChild(month);
    }

    // Done if mosaic isn't enabled or no filled image yet
    if (!enabledToggle || !enabledToggle.checked || !fillFn) return;

    // Lay out completes synchronously — measure now.
    requestAnimationFrame(function () {
      var gridRect = box.getBoundingClientRect();
      var W = Math.round(gridRect.width);
      var H = Math.round(gridRect.height);
      if (W < 10 || H < 10) return;

      var filledImg = 'url("/customization/uploads/' + fillFn + '")';
      var emptyImage = null;
      var emptyColor = null;
      if (mosaicEmptyMode === 'image' && emptyFn) {
        emptyImage = 'url("/customization/uploads/' + emptyFn + '")';
      } else if (mosaicEmptyMode === 'gradient') {
        var f = (document.getElementById('cz-mosaic-empty-grad-from') || {}).value || '#fff';
        var t = (document.getElementById('cz-mosaic-empty-grad-to')   || {}).value || '#ddd';
        var a = (document.getElementById('cz-mosaic-empty-grad-angle') || {}).value || '180';
        emptyImage = 'linear-gradient(' + a + 'deg, ' + f + ', ' + t + ')';
      } else if (mosaicEmptyMode === 'color') {
        emptyColor = (document.getElementById('cz-mosaic-empty-color') || {}).value || '';
      }

      box.querySelectorAll('.preview-mini-cube').forEach(function (cube) {
        var r = cube.getBoundingClientRect();
        var x = Math.round(r.left - gridRect.left);
        var y = Math.round(r.top - gridRect.top);
        var sizeStr = W + 'px ' + H + 'px';
        var posStr = (-x) + 'px ' + (-y) + 'px';
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
          cube.style.backgroundImage = '';
          cube.style.backgroundColor = emptyColor;
        } else {
          cube.style.backgroundImage = '';
          cube.style.backgroundColor = '';
        }
      });
    });
  }

  // Activate initial empty-mode pane and render preview on load
  setMosaicEmptyMode(mosaicEmptyMode);
  delete dirtyKeys['mosaic-empty-mode'];  // initial setup, not a real change
  renderMosaicPreview();

  // ── Repaint on changes ───────────────────────────────────────
  // Map key prefix → chart id (matching `data-chart` and CHART_RENDERERS).
  // Lets a single picker change trigger only the relevant chart redraw.
  // Most charts have prefix === id, but a few diverge (ridge / az) so we
  // use an explicit lookup table instead of a bare string transform.
  var CHART_PREFIX_TO_ID = {
    'river-':    'river',
    'spiral-':   'spiral',
    'rhythm-':   'rhythm',
    'rose-':     'rose',
    'ridge-':    'ridgeline',
    'overview-': 'overview',
    'az-':       'activities-zoom',
  };

  function chartIdForKey(key) {
    for (var prefix in CHART_PREFIX_TO_ID) {
      if (CHART_PREFIX_TO_ID.hasOwnProperty(prefix) && key.indexOf(prefix) === 0) {
        return CHART_PREFIX_TO_ID[prefix];
      }
    }
    return null;
  }

  function renderChartById(id) {
    var svg = document.querySelector('[data-chart="' + id + '"]');
    if (!svg) return;
    var renderer = CHART_RENDERERS[id];
    if (renderer) renderer(svg);
  }

  function onPreviewChange(key) {
    // Any change to the effective background should re-evaluate the
    // auto-invert decision so the live preview matches what the server
    // will emit on the next render.
    if (key === 'bg-color' || key === 'bg-type' ||
        key.indexOf('bg-gradient-') === 0) {
      applyAutoInvert();
    }
    // Mini-calendar uses pure CSS, no JS redraw.
    if (key.indexOf('neural-') === 0 || key === 'text-color' || key === 'text-muted') {
      renderNeural();
      return;
    }
    // Per-chart keys: redraw only the matching preview.
    var chartId = chartIdForKey(key);
    if (chartId) {
      renderChartById(chartId);
      return;
    }
    // Global chart-color / chart-grid-color: redraw every chart preview
    // (they're the fallback colour for any chart without a per-chart
    // override, so a global change can move multiple charts at once).
    if (key === 'chart-color' || key === 'chart-grid-color') {
      renderAllCharts();
    }
  }

  function renderAll() {
    renderCalendar();
    renderAllCharts();
    renderNeural();
    applyAutoInvert();
  }

  // Re-render on resize (canvas needs to scale)
  window.addEventListener('resize', function () {
    renderAllCharts();
    renderNeural();
  });

  // Activate the current bg-type pane and compose the initial bg-image var
  if (bgTypeHidden) {
    var initialType = bgTypeHidden.value || 'color';
    // setBgType marks dirty — undo that since this is the initial state
    setBgType(initialType);
    delete dirtyKeys['bg-type'];
  }
  rebuildBgImageVar();

  // Initial render of mini-previews
  renderAll();
}());
