import tempfile
import unittest
from pathlib import Path

from find_leads import load_keywords, partner_match, normalize


class LeadFinderTests(unittest.TestCase):
    def test_keywords_load(self):
        keywords = load_keywords()
        self.assertEqual(set(keywords), {"Shiftr", "Paxus", "Thorio", "Astrivon Labs"})
        self.assertIn("developer", [word.lower() for word in keywords["Shiftr"]])

    def test_partner_matching(self):
        keywords = load_keywords()
        self.assertEqual(partner_match("We need a dev agency to build our MVP", keywords), "Astrivon Labs")

    def test_duplicates_are_skipped(self):
        already_saved_posts = {"https://x.com/example/status/123"}
        already_saved_handles = {"example"}
        post_url, handle = "https://x.com/example/status/123", "Example"
        duplicate = normalize(post_url) in already_saved_posts or normalize(handle).lstrip("@") in already_saved_handles
        self.assertTrue(duplicate)


if __name__ == "__main__":
    unittest.main()
