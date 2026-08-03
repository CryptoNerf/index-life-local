/**
 * The note editor stores Markdown, but colour and fill are HTML-only marks.
 * These tests load the real bundle and the real init file in jsdom and check
 * that a coloured note survives the save → reload round trip, and that plain
 * notes are unaffected by the `html: true` markdown setting they required.
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { JSDOM } = require('jsdom');

const ROOT = path.join(__dirname, '..');
const BUNDLE = fs.readFileSync(path.join(ROOT, 'app/static/js/tiptap-bundle.js'), 'utf8');
const INIT = fs.readFileSync(path.join(ROOT, 'app/static/js/tiptap-editor-init.js'), 'utf8');

function makeEditor(initialContent = '') {
  const dom = new JSDOM(
    '<!doctype html><html><body><div id="editor"></div></body></html>',
    { runScripts: 'outside-only', pretendToBeVisual: true }
  );
  dom.window.eval(BUNDLE);
  dom.window.eval(INIT);
  const editor = dom.window.initTiptapEditor({
    elementId: 'editor',
    placeholderText: 'placeholder',
  });
  // The page loads the note inside the editor's onCreate hook; that hook
  // doesn't fire under jsdom, so drive the same command directly — this is
  // exactly the call initTiptapEditor makes.
  if (initialContent) editor.commands.setContent(initialContent);
  return { dom, editor };
}

function markdownOf(editor) {
  return editor.storage.markdown.getMarkdown();
}

test('text colour survives the markdown round trip', () => {
  const { editor } = makeEditor();
  editor.commands.setContent('<p>plain and coloured</p>');
  editor.commands.selectAll();
  editor.chain().setColor('#c0392b').run();

  const saved = markdownOf(editor);
  assert.match(saved, /color:\s*(#c0392b|rgb\(192,\s*57,\s*43\))/i);

  // Reload exactly the way the page does: markdown back into a fresh editor.
  const reloaded = makeEditor(saved);
  assert.match(reloaded.editor.getHTML(), /color:\s*(#c0392b|rgb\(192,\s*57,\s*43\))/i);
});

test('background fill survives the markdown round trip', () => {
  const { editor } = makeEditor();
  editor.commands.setContent('<p>filled text</p>');
  editor.commands.selectAll();
  editor.chain().setBackgroundColor('#e0c14a').run();

  const saved = markdownOf(editor);
  assert.match(saved, /background-color:\s*(#e0c14a|rgb\(224,\s*193,\s*74\))/i);

  const reloaded = makeEditor(saved);
  assert.match(reloaded.editor.getHTML(), /background-color:\s*(#e0c14a|rgb\(224,\s*193,\s*74\))/i);
});

test('clearing colour and fill leaves plain markdown behind', () => {
  const { editor } = makeEditor();
  editor.commands.setContent('<p>text</p>');
  editor.commands.selectAll();
  editor.chain().setColor('#c0392b').setBackgroundColor('#e0c14a').run();
  editor.commands.selectAll();
  editor.chain().unsetColor().unsetBackgroundColor().run();

  assert.equal(markdownOf(editor).trim(), 'text');
});

test('ordinary markdown is unchanged by allowing inline HTML', () => {
  const source = [
    '# Heading',
    '',
    'Some **bold** and *italic* text with a [link](https://example.com).',
    '',
    '- one',
    '- two',
    '',
    '> quote',
  ].join('\n');
  const { editor } = makeEditor(source);
  const out = markdownOf(editor);

  assert.match(out, /^# Heading/m);
  assert.match(out, /\*\*bold\*\*/);
  assert.match(out, /\[link\]\(https:\/\/example\.com\)/);
  assert.match(out, /^- one$/m);
  assert.match(out, /^> quote$/m);
});

test('a note that merely contains angle brackets keeps its text', () => {
  const original = 'Условие: a < b и b > c';
  const { editor } = makeEditor(original);
  // The serialiser escapes the brackets (`a &lt; b`) now that inline HTML is
  // allowed — what matters is that a save→load cycle gives the text back and
  // then stays put, rather than escaping the escapes on every save.
  const once = markdownOf(editor);
  const first = makeEditor(once);
  assert.equal(first.editor.getText(), original);
  const twice = markdownOf(first.editor);
  assert.equal(twice, once);
});

test('the toolbar swatches drive the editor', () => {
  const dom = new JSDOM(
    `<!doctype html><html><body>
       <div class="formatting-toolbar">
         <button class="format-btn" data-format="clear-color"></button>
         <label><input type="color" data-format="color" value="#123456"></label>
         <label><input type="color" data-format="fill" value="#abcdef"></label>
       </div>
       <div id="editor"></div>
     </body></html>`,
    { runScripts: 'outside-only', pretendToBeVisual: true }
  );
  dom.window.eval(BUNDLE);
  dom.window.eval(INIT);
  const editor = dom.window.initTiptapEditor({ elementId: 'editor', placeholderText: 'p' });
  editor.commands.setContent('<p>text</p>');
  const toolbar = dom.window.document.querySelector('.formatting-toolbar');
  dom.window.setupToolbarButtons(editor, toolbar);

  editor.commands.selectAll();
  const fire = (sel) => {
    const el = dom.window.document.querySelector(sel);
    el.dispatchEvent(new dom.window.Event('input', { bubbles: true }));
  };
  fire('[data-format="color"]');
  assert.match(editor.getHTML(), /color:\s*(#123456|rgb\(18,\s*52,\s*86\))/i);

  editor.commands.selectAll();
  fire('[data-format="fill"]');
  assert.match(editor.getHTML(), /background-color:\s*(#abcdef|rgb\(171,\s*205,\s*239\))/i);

  editor.commands.selectAll();
  dom.window.document.querySelector('[data-format="clear-color"]').click();
  const cleared = editor.getHTML();
  assert.ok(!/color:/i.test(cleared), `expected no colour left, got ${cleared}`);
});
