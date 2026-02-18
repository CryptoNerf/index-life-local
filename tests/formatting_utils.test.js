const test = require('node:test');
const assert = require('node:assert/strict');

const {
  renumberOrderedLists,
  normalizeMarkdown
} = require('../app/static/js/formatting_utils.js');

test('renumberOrderedLists renumbers each contiguous list block', () => {
  const input = [
    '2. two',
    '4. four',
    '',
    '3. three',
    '5. five'
  ].join('\n');
  const expected = [
    '1. two',
    '2. four',
    '',
    '1. three',
    '2. five'
  ].join('\n');

  assert.equal(renumberOrderedLists(input), expected);
});

test('normalizeMarkdown removes blank lines between list items', () => {
  const input = '- a\n\n- b\n\n- c';
  const expected = '- a\n- b\n- c';
  assert.equal(normalizeMarkdown(input), expected);
});

test('normalizeMarkdown normalizes blockquote spacing', () => {
  const input = '>quote';
  const expected = '> quote';
  assert.equal(normalizeMarkdown(input), expected);
});

test('normalizeMarkdown keeps blank lines inside code fences', () => {
  const input = [
    '```',
    'line1',
    '',
    'line2',
    '```'
  ].join('\n');
  const output = normalizeMarkdown(input);
  assert.ok(output.includes('line1\n\nline2'));
});

test('normalizeMarkdown removes empty lines outside code fences by default', () => {
  const input = 'line1\n\n\nline2';
  const expected = 'line1\nline2';
  assert.equal(normalizeMarkdown(input), expected);
});
