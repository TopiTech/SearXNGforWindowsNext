import sys
import re

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "tools")
from query_pipeline import QueryProcessor

p0 = QueryProcessor.COMPARISON_PATTERNS[0]
p1 = QueryProcessor.COMPARISON_PATTERNS[1]

# Challenger M1-1's proposed p1
p1_challenger = re.compile(
    r"([^\sと対]{1,50}+)\s*(と|VS|対)\s*([^\sと対の比較違いどっち]{1,50}+)\s*(?:の\s*)?(比較|違い|どっち)",
    re.IGNORECASE,
)

queries = [
    "Python vs Rust",
    "Python VS Rust",
    "Python vs. Rust",
    "Python versus Rust",
    "Python compared to Rust",
    '"Python" vs "Rust"',
    "「Python」 vs 「Rust」",
    "「Python」vs「Rust」",
    "PythonとRustの比較",
    "「Python」と「Rust」の比較",
    "『Python』と『Rust』の比較",
    "【Python】と【Rust】の比較",
    "“Python”と“Rust”の比較",
    "‘Python’と‘Rust’の比較",
    '"Python"と"Rust"の比較',
    "VueとReactの違い",
    "「Vue」と「React」の違い",
    "Mac対Windowsどっち",
    "「Mac」対「Windows」どっち",
    "iPhone対Android比較",
    "FastAPIとDjangoの比較",
    "Python vs Rust 比較",
    "Python vs Rust の比較",
    "「Python」 vs 「Rust」 比較",
]

print(f"{'Query':<30} | {'P0':<6} | {'P1 (cur)':<8} | {'P1 (chal)':<10}")
print("-" * 65)
for q in queries:
    pq = QueryProcessor.parse_and_normalize(q)
    target = pq.clean_no_quotes.lower()
    m0 = bool(p0.search(target))
    m1 = bool(p1.search(target))
    m1_c = bool(p1_challenger.search(target))
    print(f"{q:<30} | {str(m0):<6} | {str(m1):<8} | {str(m1_c):<10}")
