// Entry file for Tiptap bundle
import { Editor } from '@tiptap/core';
import StarterKit from '@tiptap/starter-kit';
import Placeholder from '@tiptap/extension-placeholder';
import Typography from '@tiptap/extension-typography';
import { Markdown } from 'tiptap-markdown';

// Export to window for global access
window.TiptapEditor = Editor;
window.TiptapStarterKit = StarterKit;
window.TiptapPlaceholder = Placeholder;
window.TiptapTypography = Typography;
window.TiptapMarkdown = Markdown;
