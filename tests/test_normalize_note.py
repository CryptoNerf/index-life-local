import unittest

from app.routes import normalize_note


class NormalizeNoteTests(unittest.TestCase):
    def test_removes_blank_lines_between_list_items(self):
        text = "- a\n\n- b\n\n- c"
        self.assertEqual(normalize_note(text), "- a\n- b\n- c")

    def test_renumbers_ordered_lists(self):
        text = "2. two\n4. four\n\n3. three\n5. five"
        expected = "1. two\n2. four\n3. three\n4. five"
        self.assertEqual(normalize_note(text), expected)

    def test_collapses_multiple_blank_lines(self):
        text = "line1\n\n\nline2\n\n"
        self.assertEqual(normalize_note(text), "line1\n\nline2")

    def test_preserves_code_fence_blank_lines(self):
        text = "```\nline1\n\nline2\n```"
        self.assertEqual(normalize_note(text), "```\nline1\n\nline2\n```")

    def test_preserves_blank_line_around_blockquote(self):
        text = "before\n\n> quote\n\nafter"
        self.assertEqual(normalize_note(text), "before\n\n> quote\n\nafter")

    def test_preserves_blank_line_around_heading(self):
        text = "before\n\n## heading\n\nafter"
        self.assertEqual(normalize_note(text), "before\n\n## heading\n\nafter")

    def test_no_consecutive_blank_lines(self):
        text = "a\n\n\n\n\nb"
        self.assertEqual(normalize_note(text), "a\n\nb")


if __name__ == "__main__":
    unittest.main()
