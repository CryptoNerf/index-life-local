/* Tiptap Editor Initialization with Native Markdown Support */
/* globals TiptapEditor, TiptapStarterKit, TiptapPlaceholder, TiptapTypography, TiptapMarkdown */

function initTiptapEditor(options) {
  const {
    elementId,
    placeholderText = 'Write your note here...',
    initialContent = '',
    onUpdate = null,
    lang = 'ru'
  } = options;

  // Typography turns typed straight double quotes into typographic ones; in
  // Russian those are «ёлочки», not the English “…”. Single quotes keep the
  // default: in a Russian note they are mostly apostrophes (don't, O'Brien).
  const quotes = lang === 'ru'
    ? { openDoubleQuote: '«', closeDoubleQuote: '»' }
    : {};

  const element = document.getElementById(elementId);
  if (!element) {
    console.error('Tiptap: Element not found:', elementId);
    return null;
  }

  const editor = new window.TiptapEditor({
    element: element,
    extensions: [
      window.TiptapStarterKit.configure({
        heading: { levels: [1, 2, 3] },
      }),
      window.TiptapPlaceholder.configure({
        placeholder: placeholderText,
      }),
      window.TiptapTypography.configure(quotes),
      window.TiptapMarkdown.configure({
        html: false,               // Не разрешать сырой HTML в Markdown
        tightLists: true,
        bulletListMarker: '-',
        linkify: true,
        breaks: true,              // Одинарный перенос → <br>
        transformPastedText: true,
        transformCopiedText: true,
      }),
    ],

    // Инициализируем с пустым контентом — Markdown загружается через onCreate
    content: '',

    editorProps: {
      attributes: {
        class: 'tiptap-editor-content',
      },
      // The quote shortcut does what the quote button does (toggleQuote),
      // not Tiptap's whole-paragraph toggle.
      handleKeyDown: (view, event) => {
        if ((event.metaKey || event.ctrlKey) && event.shiftKey && event.code === 'KeyB') {
          toggleQuote(editor);
          return true;
        }
        return false;
      },
      // Стандартное поведение Tiptap: Enter = новый параграф (виден как разрыв
      // с отступом — см. margin на .ProseMirror p в tiptap-custom.css, как в
      // отображении заметки). Цитата оборачивает параграф целиком, поэтому
      // видимый разрыв делает поведение цитаты предсказуемым.
      // Shift+Enter = hard break (<br>) внутри параграфа.
    },

    // Загружаем Markdown контент после того как расширение инициализировано
    onCreate: ({ editor }) => {
      if (initialContent && initialContent.trim()) {
        editor.commands.setContent(initialContent);
      }
    },

    onUpdate: ({ editor }) => {
      if (onUpdate) {
        const markdown = editor.storage.markdown.getMarkdown();
        onUpdate(markdown, editor);
      }
    },
  });

  return editor;
}

function getMarkdownFromEditor(editor) {
  if (!editor || !editor.storage || !editor.storage.markdown) {
    console.error('Tiptap: Markdown extension not loaded');
    return '';
  }
  return editor.storage.markdown.getMarkdown();
}

/* ── Quoting exactly what is selected ──────────────────────────────────
   A quote is a block, and Tiptap's toggleBlockquote wraps the WHOLE
   paragraph. A note written line by line (Shift+Enter, or plain newlines
   from the phone) is one paragraph with line breaks, so selecting one line
   and pressing the quote button quoted the entire note. Here the paragraph
   is first cut at the edges of the selection (or, with nothing selected, at
   the edges of the line the cursor is on), and only that part is quoted.
   The same cut works the other way: unquoting one line of a long quote
   takes out that line, not the whole quote. */

const QUOTE_HOSTS = new Set(['doc', 'blockquote']);

function isPlainParagraph($pos) {
  return $pos.parent.type.name === 'paragraph'
    && QUOTE_HOSTS.has($pos.node(-1).type.name);
}

// [from, to] of the line around `$pos`: between the hard breaks (or the
// paragraph's edges) on either side of the cursor.
function lineAround($pos) {
  const para = $pos.parent;
  const start = $pos.start();
  let lineStart = 0;
  let lineEnd = para.content.size;
  let offset = 0;
  para.forEach((child) => {
    if (child.type.name === 'hardBreak') {
      if (offset < $pos.parentOffset) lineStart = offset + 1;
      else if (lineEnd === para.content.size) lineEnd = offset;
    }
    offset += child.nodeSize;
  });
  return [start + lineStart, start + lineEnd];
}

// Split the paragraph at `pos`, unless `pos` is already at one of its edges.
// A hard break at the cut becomes the paragraph boundary itself, and the
// space left over by cutting mid-sentence goes with it.
function cutAt(tr, pos) {
  let $p = tr.doc.resolve(pos);
  if ($p.parent.type.name !== 'paragraph') return;
  const atEdge = (p) => p.parentOffset === 0 || p.parentOffset === p.parent.content.size;
  if (atEdge($p)) return;
  if ($p.nodeAfter && $p.nodeAfter.type.name === 'hardBreak') {
    tr.delete(pos, pos + 1);
  } else if ($p.nodeBefore && $p.nodeBefore.type.name === 'hardBreak') {
    tr.delete(pos - 1, pos);
    pos -= 1;
  }
  $p = tr.doc.resolve(pos);
  if (atEdge($p)) return;
  // A space on either side of a mid-sentence cut would be left dangling.
  if (tr.doc.textBetween(pos, pos + 1) === ' ') tr.delete(pos, pos + 1);
  if (tr.doc.textBetween(pos - 1, pos) === ' ') { tr.delete(pos - 1, pos); pos -= 1; }
  $p = tr.doc.resolve(pos);
  if (atEdge($p)) return;
  tr.split(pos);
}

// Cut out of its paragraph exactly what a block format should apply to:
// the selection, trimmed, or with nothing selected the line the cursor is
// on. With `eachLine`, the line breaks inside it become paragraph breaks
// too, so that every selected line becomes its own heading or list item.
// Returns the range of the result, ready for the format to be applied.
function isolateLines(editor, { eachLine = false } = {}) {
  const { state } = editor;
  const sel = state.selection;
  let from = sel.from;
  let to = sel.to;
  if (sel.empty) {
    [from, to] = lineAround(sel.$from);
  } else {
    // Whitespace at the edges of a selection is not part of it.
    const text = state.doc.textBetween(from, to, '\n', '\n');
    from += text.length - text.trimStart().length;
    to -= text.length - text.trimEnd().length;
    if (to <= from) [from, to] = lineAround(sel.$from);
  }

  const tr = state.tr;
  cutAt(tr, to);
  cutAt(tr, from);
  let start = tr.mapping.map(from, 1);
  let end = Math.max(start, tr.mapping.map(to, -1));
  if (eachLine) {
    const breaks = [];
    tr.doc.nodesBetween(start, end, (node, pos) => {
      if (node.type.name === 'hardBreak') breaks.push(pos);
    });
    for (const pos of breaks.reverse()) {
      tr.delete(pos, pos + 1);
      tr.split(pos);
    }
    // The splits come after `start`, so only the end moves.
    end = Math.max(start, tr.mapping.map(to, -1));
  }
  editor.view.dispatch(tr);
  return { from: start, to: end };
}

// Selection wholly inside top-level (or quoted) paragraphs: the case where
// Tiptap's own toggles take a whole multi-line paragraph.
function inPlainParagraphs(editor) {
  const sel = editor.state.selection;
  return isPlainParagraph(sel.$from) && isPlainParagraph(sel.$to);
}

function toggleQuote(editor) {
  const sel = editor.state.selection;
  if (!inPlainParagraphs(editor)) {
    // Headings, code: the standard whole-block behaviour.
    if (editor.chain().focus().toggleBlockquote().run()) return true;
    // A list item cannot hold a quote of its first line, and the button
    // used to do nothing at all there. Quote the whole list instead.
    if (sel.$from.depth < 1) return false;
    return editor.chain().focus()
      .setNodeSelection(sel.$from.before(1))
      .wrapIn('blockquote')
      .run();
  }
  const unquote = editor.isActive('blockquote');
  const range = isolateLines(editor);
  const chain = editor.chain().focus().setTextSelection(range);
  return (unquote ? chain.lift('blockquote') : chain.wrapIn('blockquote')).run();
}

// Headings and lists had the same flaw as quotes: on a note written line by
// line, H2 or "• Список" on one line turned the whole note into a heading
// or into one list item. Now they apply to the selected lines, one heading
// or one item per line. Turning a format off keeps Tiptap's behaviour.
function toggleLinesFormat(editor, apply) {
  if (!inPlainParagraphs(editor)) return apply(editor.chain().focus()).run();
  const range = isolateLines(editor, { eachLine: true });
  return apply(editor.chain().focus().setTextSelection(range)).run();
}

function setupToolbarButtons(editor, toolbarElement) {
  const buttons = toolbarElement.querySelectorAll('.format-btn');

  buttons.forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      const format = btn.dataset.format;

      switch (format) {
        case 'bold':
          editor.chain().focus().toggleBold().run();
          break;
        case 'italic':
          editor.chain().focus().toggleItalic().run();
          break;
        case 'h1':
          toggleLinesFormat(editor, (c) => c.toggleHeading({ level: 1 }));
          break;
        case 'h2':
          toggleLinesFormat(editor, (c) => c.toggleHeading({ level: 2 }));
          break;
        case 'h3':
          toggleLinesFormat(editor, (c) => c.toggleHeading({ level: 3 }));
          break;
        case 'list':
          toggleLinesFormat(editor, (c) => c.toggleBulletList());
          break;
        case 'numbered':
          toggleLinesFormat(editor, (c) => c.toggleOrderedList());
          break;
        case 'link': {
          const url = prompt(window.LINK_PROMPT || 'Enter URL:', 'https://');
          if (url && url.trim()) {
            editor.chain().focus().setLink({ href: url.trim() }).run();
          }
          break;
        }
        case 'quote':
          toggleQuote(editor);
          break;
        case 'strike':
          editor.chain().focus().toggleStrike().run();
          break;
        case 'code':
          editor.chain().focus().toggleCode().run();
          break;
        case 'hr':
          editor.chain().focus().setHorizontalRule().run();
          break;
      }
    });
  });

  editor.on('selectionUpdate', () => updateToolbarState(editor, buttons));
  editor.on('update', () => updateToolbarState(editor, buttons));
}

function updateToolbarState(editor, buttons) {
  buttons.forEach(btn => {
    const format = btn.dataset.format;
    let isActive = false;

    switch (format) {
      case 'bold':    isActive = editor.isActive('bold'); break;
      case 'italic':  isActive = editor.isActive('italic'); break;
      case 'h1':      isActive = editor.isActive('heading', { level: 1 }); break;
      case 'h2':      isActive = editor.isActive('heading', { level: 2 }); break;
      case 'h3':      isActive = editor.isActive('heading', { level: 3 }); break;
      case 'list':    isActive = editor.isActive('bulletList'); break;
      case 'numbered':isActive = editor.isActive('orderedList'); break;
      case 'quote':   isActive = editor.isActive('blockquote'); break;
      case 'link':    isActive = editor.isActive('link'); break;
      case 'strike':  isActive = editor.isActive('strike'); break;
      case 'code':    isActive = editor.isActive('code'); break;
    }

    btn.classList.toggle('active-format', isActive);
  });
}

window.TiptapEditorUtils = {
  initTiptapEditor,
  setupToolbarButtons,
  getMarkdownFromEditor
};
