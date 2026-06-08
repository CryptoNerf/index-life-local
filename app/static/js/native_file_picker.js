// Native file-picker bridge for pywebview / WKWebView.
//
// WKWebView's <input type="file" accept=...> goes through a UTType
// lookup whose mapping is incomplete on the macOS versions we see:
// .webp / .gif silently disappear from "image/*", .woff / .woff2
// have no UTI at all. The dialog then either narrows to "JPG only"
// or widens to "all files". Routing through pywebview's
// `create_file_dialog` (Cocoa NSOpenPanel) with an explicit
// `*.ext;*.ext` pattern works around it.
//
// Three public entry points on `window`:
//   NFP_hasBridge()                  → boolean
//   NFP_pick(label, exts, maxBytes)  → Promise<{ name, blob } | null>
//   NFP_interceptInput(inputEl, label, exts, maxBytes)
//                                    — for classic <form><input type="file">
//                                      forms: hijack the click, populate
//                                      input.files via DataTransfer so
//                                      the existing form submit Just Works
(function () {
  function hasBridge() {
    return !!(window.pywebview && window.pywebview.api &&
              typeof window.pywebview.api.open_file_dialog === 'function');
  }

  // Resolves to { name, blob } on success, null on cancel / error
  // (errors already alerted). Caller must check hasBridge() first.
  function pick(label, exts, maxBytes) {
    return window.pywebview.api.open_file_dialog(label, exts, maxBytes)
      .then(function (picked) {
        if (!picked) return null;
        if (picked.error) {
          alert('Upload failed: ' + picked.error);
          return null;
        }
        var bin = atob(picked.base64);
        var arr = new Uint8Array(bin.length);
        for (var i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
        return { name: picked.name, blob: new Blob([arr]) };
      });
  }

  // Hijack a classic <input type="file"> so clicking opens the native
  // bridge (in pywebview) but populates input.files just like a normal
  // selection would — preserving any change-event listeners and the
  // form's multipart submission.
  function interceptInput(inputEl, label, exts, maxBytes) {
    if (!inputEl) return;
    inputEl.addEventListener('click', function (e) {
      if (!hasBridge()) return;        // browser fallback: let the
                                        // native <input> open as usual
      e.preventDefault();
      pick(label, exts, maxBytes).then(function (picked) {
        if (!picked) return;
        // Construct a File the form's existing multipart handling
        // can pick up. DataTransfer is the supported way to set
        // input.files programmatically (assigning to .files directly
        // is read-only in most browsers).
        var dt = new DataTransfer();
        var file = new File([picked.blob], picked.name);
        dt.items.add(file);
        inputEl.files = dt.files;
        // Mirror what a real selection would fire so any onchange
        // / change-listener (e.g. the filename display in account.html)
        // reacts identically.
        inputEl.dispatchEvent(new Event('change', { bubbles: true }));
      });
    });
  }

  window.NFP_hasBridge = hasBridge;
  window.NFP_pick = pick;
  window.NFP_interceptInput = interceptInput;
})();
