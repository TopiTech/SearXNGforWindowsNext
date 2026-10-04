import sys
import re

sys.stdout.reconfigure(encoding="utf-8")

# Let's test relaxing COMPARISON_PATTERNS[0] to support:
# 1. Optional quotes/brackets around tokens: ['"「『【]?
# 2. CJK / Unicode characters in item names
# 3. Optional dot in 'vs.': (vs\.?|versus|compared to)
# 4. Allowing \s* if preceded/followed by brackets, e.g. 「A」vs「B」

pat0_refined = re.compile(
    r"""
    (?:^|\s|[^\w])                 # Boundary or start
    ['"「『【]?                   # Optional opening quote/bracket
    ([a-z0-9_+#.\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff-]{1,50}+) # Item A (Latin or CJK)
    ['"」』】]?                   # Optional closing quote/bracket
    \s*(?:vs\.?|versus|compared\s+to)\s*  # vs separator (with or without dot/spaces)
    ['"「『【]?                   # Optional opening quote/bracket
    ([a-z0-9_+#.\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff-]{1,50}+) # Item B (Latin or CJK)
    ['"」』】]?                   # Optional closing quote/bracket
    (?:\s|[^\w]|$)                 # Boundary or end
    """,
    re.IGNORECASE | re.VERBOSE,
)

test_vs_queries = [
    "Python vs Rust",
    "Python vs. Rust",
    "Python VS Rust",
    "Python versus Rust",
    "Python compared to Rust",
    '"Python" vs "Rust"',
    "'Python' vs 'Rust'",
    "‘Python’ vs ‘Rust’",
    "“Python” vs “Rust”",
    "「Python」 vs 「Rust」",
    "「Python」vs「Rust」",
    "『Python』vs『Rust』",
    "【Python】vs【Rust】",
    "機械学習 vs 深層学習",
    "機械学習vs深層学習",
    "「機械学習」vs「深層学習」",
    "C++ vs Rust",
    "Node.js vs Deno",
]

print("=== PATTERN 0 (VS) REFINEMENT EVALUATION ===")
for q in test_vs_queries:
    m = pat0_refined.search(q)
    if m:
        print(f"MATCH   : {q:<30} -> ({m.group(1)!r}, {m.group(2)!r})")
    else:
        print(f"NO MATCH: {q:<30}")
