// Entry file for Tiptap bundle
import { Editor } from '@tiptap/core';
import StarterKit from '@tiptap/starter-kit';
import Placeholder from '@tiptap/extension-placeholder';
import Typography from '@tiptap/extension-typography';
import { TextStyle, Color, BackgroundColor } from '@tiptap/extension-text-style';
import { Markdown } from 'tiptap-markdown';

// Export to window for global access
window.TiptapEditor = Editor;
window.TiptapStarterKit = StarterKit;
window.TiptapPlaceholder = Placeholder;
window.TiptapTypography = Typography;
// Text colour and fill: both are TextStyle attributes, so they serialise as
// one <span style="…"> — which markdown carries through as inline HTML.
window.TiptapTextStyle = TextStyle;
window.TiptapColor = Color;
window.TiptapBackgroundColor = BackgroundColor;
window.TiptapMarkdown = Markdown;
