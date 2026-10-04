import sys
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "tools")
from query_pipeline import QueryProcessor

queries = [
    "'Python' vs 'Rust'",
    "‘Python’ vs ‘Rust’",
    "「Python」 vs 「Rust」",
    "「Python」vs「Rust」",
    "「Python」 vs 「Rust」 比較",
]
for q in queries:
    pq = QueryProcessor.parse_and_normalize(q)
    print(f"Query: {q!r} -> clean_no_quotes: {pq.clean_no_quotes!r} -> intent: {pq.intent!r}")
