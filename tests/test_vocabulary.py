import unittest

from kyoko.vocabulary import learning_terms, section_description, section_label


class VocabularyTests(unittest.TestCase):
    def test_section_labels_distinguish_context_and_harness_fixes(self) -> None:
        self.assertEqual(section_label("context"), "Context fix")
        self.assertEqual(section_label("harness"), "Harness fix")
        self.assertIn("agent-facing", section_description("context"))
        self.assertIn("eval", section_description("harness"))

    def test_unknown_sections_have_stable_fallback_copy(self) -> None:
        self.assertEqual(section_label("custom_plane"), "Custom Plane")
        self.assertEqual(section_label(None), "Unknown fix")
        self.assertIn("not recognized", section_description("custom_plane"))

    def test_learning_terms_returns_a_copy(self) -> None:
        terms = learning_terms()
        terms["context"]["label"] = "changed"

        self.assertEqual(learning_terms()["context"]["label"], "Context fix")


if __name__ == "__main__":
    unittest.main()
