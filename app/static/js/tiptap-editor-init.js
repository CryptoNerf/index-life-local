/* Tiptap Editor Initialization with Native Markdown Support */
/* globals TiptapEditor, TiptapStarterKit, TiptapPlaceholder, TiptapTypography, TiptapMarkdown */

function initTiptapEditor(options) {
  const {
    elementId,
    placeholderText = 'Write your note here...',
    initialContent = '',
    onUpdate = null
  } = options;

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
      window.TiptapTypography,
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
      // Стандартное поведение Tiptap: Enter = новый параграф.
      // Визуально как обычный перенос строки — за счёт margin: 0 на параграфах в CSS.
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
          editor.chain().focus().toggleHeading({ level: 1 }).run();
          break;
        case 'h2':
          editor.chain().focus().toggleHeading({ level: 2 }).run();
          break;
        case 'h3':
          editor.chain().focus().toggleHeading({ level: 3 }).run();
          break;
        case 'list':
          editor.chain().focus().toggleBulletList().run();
          break;
        case 'numbered':
          editor.chain().focus().toggleOrderedList().run();
          break;
        case 'link': {
          const url = prompt('Enter URL:', 'https://');
          if (url && url.trim()) {
            editor.chain().focus().setLink({ href: url.trim() }).run();
          }
          break;
        }
        case 'quote':
          editor.chain().focus().toggleBlockquote().run();
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
    }

    btn.classList.toggle('active-format', isActive);
  });
}

window.TiptapEditorUtils = {
  initTiptapEditor,
  setupToolbarButtons,
  getMarkdownFromEditor
};
