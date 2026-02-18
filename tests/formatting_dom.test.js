const test = require('node:test');
const assert = require('node:assert/strict');
const { JSDOM } = require('jsdom');

const domUtils = require('../app/static/js/formatting_dom_utils.js');

function createDom(html) {
  const dom = new JSDOM(html);
  return dom.window.document;
}

test('normalizeEditorDom converts newlines to <br> outside lists', () => {
  const document = createDom('<div id="root">line1\nline2</div>');
  const root = document.getElementById('root');

  domUtils.normalizeEditorDom(root);
  assert.equal(root.innerHTML, 'line1<br>line2');
});

test('normalizeEditorDom does not insert <br> inside list items', () => {
  const document = createDom('<ul><li id="item">1\n2</li></ul>');
  const item = document.getElementById('item');

  domUtils.normalizeEditorDom(document.body);
  assert.equal(item.innerHTML, '1 2');
  assert.equal(item.querySelectorAll('br').length, 0);
});

test('stripInterBlockWhitespace removes text nodes between list items', () => {
  const document = createDom('<ul id="list"><li>one</li>\n    <li>two</li></ul>');
  const list = document.getElementById('list');

  domUtils.normalizeEditorDom(document.body);
  const hasTextNodes = Array.from(list.childNodes).some(node => node.nodeType === 3);
  assert.equal(hasTextNodes, false);
});

test('wrapRootInlineRuns wraps inline text when block elements exist', () => {
  const document = createDom('<div id="root">intro<ul><li>item</li></ul>tail</div>');
  const root = document.getElementById('root');

  domUtils.normalizeEditorDom(root);
  const firstChild = root.firstChild;
  assert.equal(firstChild.nodeType, 1);
  assert.equal(firstChild.tagName, 'DIV');
  assert.equal(firstChild.textContent, 'intro');
});

test('hasRichFormatting detects formatting tags', () => {
  const document = createDom('<div id="root">plain</div>');
  const root = document.getElementById('root');
  assert.equal(domUtils.hasRichFormatting(root), false);

  root.innerHTML = '<strong>bold</strong>';
  assert.equal(domUtils.hasRichFormatting(root), true);
});

test('extractPlainText preserves line breaks from divs and br', () => {
  const document = createDom('<div id="root"><div>line1</div><div>line2<br>line3</div></div>');
  const root = document.getElementById('root');
  const text = domUtils.extractPlainText(root);
  assert.equal(text.trim(), 'line1\nline2\nline3');
});
