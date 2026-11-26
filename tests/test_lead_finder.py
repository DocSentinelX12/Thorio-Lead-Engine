import unittest

from find_leads import is_duplicate, load_keywords, partner_match


class LeadFinderTests(unittest.TestCase):
    def test_keywords_load(self):
        keywords = load_keywords()
        self.assertEqual(set(keywords), {"Shiftr", "Paxus", "Thorio", "Astrivon Labs"})
        self.assertIn("developer", [word.lower() for word in keywords["Shiftr"]])

    def test_partner_matching(self):
        keywords = load_keywords()
        self.assertEqual(partner_match("We need a dev agency to build our MVP", keywords), "Astrivon Labs")
        self.assertEqual(partner_match("We need contractors to help our software team", keywords), "Paxus")

    def test_duplicates_are_skipped(self):
        posts = {"https://x.com/example/status/123"}
        handles = {"example"}
        self.assertTrue(is_duplicate("https://x.com/example/status/123", "", posts, handles))
        self.assertTrue(is_duplicate("https://x.com/example/status/456", "Example", posts, handles))
        self.assertFalse(is_duplicate("https://x.com/new/status/789", "New", posts, handles))


if __name__ == "__main__":
    unittest.main()
