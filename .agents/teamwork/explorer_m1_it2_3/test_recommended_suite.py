import sys
import re
import unittest
from dataclasses import dataclass, field
from typing import ClassVar

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "tools")
from query_pipeline import QueryProcessor

# Recommended Option B / C patterns
P0_REFINED = re.compile(
    r"(?:^|\s|[^\w])['\"「『【]?([a-z0-9_+#.\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff-]{1,50}+)['\"」』】]?\s*(?:vs\.?|versus|compared\s+to)\s*['\"「『【]?([a-z0-9_+#.\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff-]{1,50}+)['\"」』】]?(?:\s|[^\w]|$)",
    re.IGNORECASE,
)

P1_REFINED = re.compile(
    r"([^\sと対]{1,50}+)\s*(と|VS|対)\s*([^\sと対]{1,50}?)\s*(?:の\s*)?(比較|違い|どっち)",
    re.IGNORECASE,
)

class RecommendedPatternTestSuite(unittest.TestCase):
    def test_english_standard(self):
        m = P0_REFINED.search("Python vs Rust")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "Python")
        self.assertEqual(m.group(2), "Rust")

    def test_english_quotes(self):
        m = P0_REFINED.search('"Python" vs "Rust"')
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "Python")
        self.assertEqual(m.group(2), "Rust")

    def test_english_single_quotes(self):
        m = P0_REFINED.search("'Python' vs 'Rust'")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "Python")
        self.assertEqual(m.group(2), "Rust")

    def test_japanese_kagi_vs(self):
        m = P0_REFINED.search("「Python」 vs 「Rust」")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "Python")
        self.assertEqual(m.group(2), "Rust")

    def test_japanese_kagi_vs_unspaced(self):
        m = P0_REFINED.search("「Python」vs「Rust」")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "Python")
        self.assertEqual(m.group(2), "Rust")

    def test_cjk_vs(self):
        m = P0_REFINED.search("機械学習 vs 深層学習")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "機械学習")
        self.assertEqual(m.group(2), "深層学習")

    def test_japanese_unspaced(self):
        m = P1_REFINED.search("PythonとRustの比較")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "Python")
        self.assertEqual(m.group(3), "Rust")

    def test_japanese_kagi_unspaced(self):
        m = P1_REFINED.search("「Python」と「Rust」の比較")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1).strip("「」"), "Python")
        self.assertEqual(m.group(3).strip("「」"), "Rust")

    def test_japanese_entity_with_no_particle(self):
        m = P1_REFINED.search("呪術廻戦と鬼滅の刃の比較")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "呪術廻戦")
        self.assertEqual(m.group(3), "鬼滅の刃")

    def test_japanese_entity_with_no_particle_in_brackets(self):
        m = P1_REFINED.search("「呪術廻戦」と「鬼滅の刃」の比較")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1).strip("「」"), "呪術廻戦")
        self.assertEqual(m.group(3).strip("「」"), "鬼滅の刃")

    def test_japanese_spaced(self):
        m = P1_REFINED.search("Python と Rust 比較")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "Python")
        self.assertEqual(m.group(3), "Rust")

    def test_japanese_vs_comparison(self):
        m = P1_REFINED.search("Python VS Rust の比較")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "Python")
        self.assertEqual(m.group(3), "Rust")

    def test_tai_comparison(self):
        m = P1_REFINED.search("Mac対Windowsどっち")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "Mac")
        self.assertEqual(m.group(3), "Windows")

if __name__ == "__main__":
    unittest.main()
