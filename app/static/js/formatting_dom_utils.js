/* DOM formatting utilities shared between editor and tests */
(function(root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.FormattingDomUtils = factory();
  }
})(typeof self !== 'undefined' ? self : this, function() {
  function stripInterBlockWhitespace(root) {
    const containers = [root, ...root.querySelectorAll('ul, ol, blockquote')];
    containers.forEach(container => {
      Array.from(container.childNodes).forEach(node => {
        if (node.nodeType === 3 && !node.textContent.trim()) {
          container.removeChild(node);
        }
      });
    });
  }

  function wrapRootInlineRuns(root) {
    const blockTags = new Set(['div', 'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'ul', 'ol', 'li', 'blockquote', 'hr', 'pre']);
    const children = Array.from(root.childNodes);
    const hasBlock = children.some(node => (
      node.nodeType === 1 && blockTags.has(node.tagName.toLowerCase())
    ));

    if (!hasBlock) return;

    let buffer = [];
    function flushBuffer(beforeNode) {
      if (!buffer.length) return;
      const div = root.ownerDocument.createElement('div');
      buffer.forEach(node => div.appendChild(node));
      root.insertBefore(div, beforeNode || null);
      buffer = [];
    }

    children.forEach(node => {
      if (node.nodeType === 3 && !node.textContent.trim()) {
        root.removeChild(node);
        return;
      }

      if (node.nodeType === 1 && blockTags.has(node.tagName.toLowerCase())) {
        flushBuffer(node);
        return;
      }

      buffer.push(node);
    });

    flushBuffer(null);
  }

  function convertTextNewlinesToBreaks(node) {
    const children = Array.from(node.childNodes);
    children.forEach(child => {
      if (child.nodeType === 3) {
        const text = child.nodeValue || '';
        if (!text.includes('\n')) return;

        if (!text.trim()) {
          child.parentNode.removeChild(child);
          return;
        }

        if (child.parentNode && child.parentNode.closest && child.parentNode.closest('li')) {
          const normalized = text.replace(/\n+/g, ' ').replace(/\s{2,}/g, ' ');
          child.nodeValue = normalized;
          return;
        }

        const parts = text.split(/\n/);
        const frag = node.ownerDocument.createDocumentFragment();

        parts.forEach((part, index) => {
          if (part) {
            frag.appendChild(node.ownerDocument.createTextNode(part));
          }
          if (index < parts.length - 1) {
            frag.appendChild(node.ownerDocument.createElement('br'));
          }
        });

        child.parentNode.replaceChild(frag, child);
        return;
      }

      if (child.nodeType === 1) {
        convertTextNewlinesToBreaks(child);
      }
    });
  }

  function normalizeEditorDom(root) {
    wrapRootInlineRuns(root);
    convertTextNewlinesToBreaks(root);
    stripInterBlockWhitespace(root);
  }

  function getNormalizedEditorHtml(root) {
    const clone = root.cloneNode(true);
    normalizeEditorDom(clone);
    return clone.innerHTML;
  }

  function hasRichFormatting(root) {
    if (!root || !root.querySelector) return false;
    const richSelector = [
      'strong', 'b', 'em', 'i', 'u',
      's', 'del', 'strike',
      'a', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
      'ul', 'ol', 'li',
      'blockquote', 'pre', 'code'
    ].join(',');
    return root.querySelector(richSelector) !== null;
  }

  function extractPlainText(root) {
    if (!root) return '';

    function walk(node) {
      let out = '';
      node.childNodes.forEach(child => {
        if (child.nodeType === 3) {
          out += child.nodeValue || '';
          return;
        }
        if (child.nodeType !== 1) return;

        const tag = child.tagName.toLowerCase();
        if (tag === 'br') {
          out += '\n';
          return;
        }

        out += walk(child);

        if (tag === 'div' || tag === 'p') {
          out += '\n';
        }
      });
      return out;
    }

    return walk(root);
  }

  return {
    stripInterBlockWhitespace,
    wrapRootInlineRuns,
    convertTextNewlinesToBreaks,
    normalizeEditorDom,
    getNormalizedEditorHtml,
    hasRichFormatting,
    extractPlainText
  };
});
