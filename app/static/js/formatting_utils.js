/* Formatting utilities shared between editor and tests */
(function(root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.FormattingUtils = factory();
  }
})(typeof self !== 'undefined' ? self : this, function() {
  function renumberOrderedLists(markdown) {
    const lines = (markdown || '').split('\n');
    const output = [];
    let inList = false;
    let currentIndent = '';
    let counter = 1;

    lines.forEach(line => {
      const match = line.match(/^(\s*)(\d+)\.\s+(.*)$/);
      if (match) {
        const indent = match[1] || '';
        const content = match[3];
        if (!inList || indent !== currentIndent) {
          inList = true;
          currentIndent = indent;
          counter = 1;
        }
        output.push(`${indent}${counter}. ${content}`);
        counter += 1;
        return;
      }

      inList = false;
      currentIndent = '';
      counter = 1;
      output.push(line);
    });

    return output.join('\n');
  }

  function normalizeMarkdown(markdown, options) {
    const settings = options || {};
    const removeEmptyLines = settings.removeEmptyLines !== false;
    let result = (markdown || '')
      .replace(/[\u200B-\u200D\uFEFF]/g, '')
      .replace(/\u00a0/g, ' ')
      .replace(/\r\n?/g, '\n');

    // Collapse blank lines between list items (ordered or unordered)
    result = result.replace(
      /(^\s*(?:-|\d+\.)\s+.*)\n\s*\n(?=\s*(?:-|\d+\.)\s+)/gm,
      '$1\n'
    );
    result = renumberOrderedLists(result);
    const lines = result.split('\n');
    let inCodeFence = false;

    const normalized = lines.map(line => {
      const scrubbedLine = line.replace(/[\u200B-\u200D\uFEFF]/g, '');
      line = scrubbedLine;
      const fenceMatch = line.match(/^\s*```/);
      if (fenceMatch) {
        inCodeFence = !inCodeFence;
        return line.trim();
      }

      if (inCodeFence) {
        return line.replace(/[ \t]+$/g, '');
      }

      if (!line.trim()) return '';

      if (line.trim().startsWith('>')) {
        const rest = line.replace(/^\s*>\s?/, '');
        return rest.trim() ? '> ' + rest.trim() : '>';
      }

      const listMatch = line.match(/^(\s*)(-|\d+\.)\s*(.*)$/);
      if (listMatch) {
        const indent = listMatch[1] || '';
        const marker = listMatch[2];
        const rest = listMatch[3].trim();
        return indent + marker + (rest ? ' ' + rest : '');
      }

      if (line.startsWith('  ')) {
        return '  ' + line.slice(2).trim();
      }

      return line.trim();
    });

    let output = [];
    let inFence = false;

    for (const line of normalized) {
      if (/^\s*```/.test(line)) {
        inFence = !inFence;
        output.push(line);
        continue;
      }

      if (inFence) {
        output.push(line);
        continue;
      }

      if (removeEmptyLines) {
        if (line === '') continue;
        output.push(line);
        continue;
      }

      if (line === '') {
        if (output.length && output[output.length - 1] === '') continue;
        output.push('');
        continue;
      }

      output.push(line);
    }

    result = output.join('\n');
    result = result.replace(/[ \t]+\n/g, '\n');
    result = result.replace(/\n{3,}/g, '\n\n');
    return result.trim();
  }

  return {
    renumberOrderedLists,
    normalizeMarkdown
  };
});
