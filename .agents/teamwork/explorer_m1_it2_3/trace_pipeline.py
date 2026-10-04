import sys
import unicodedata
import re

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "tools")
from query_pipeline import QueryProcessor

# Let's inspect step-by-step
queries = [
    # 1. Plain English
    "Python vs Rust",
    # 2. English with double quotes
    '"Python" vs "Rust"',
    # 3. English with typographic quotes
    '“Python” vs “Rust”',
    # 4. Japanese with spaces
    "Python と Rust の比較",
    # 5. Natural Japanese unspaced
    "PythonとRustの比較",
    # 6. Natural Japanese with ASCII quotes
    '"Python"と"Rust"の比較',
    # 7. Natural Japanese with typographic quotes
    '“Python”と“Rust”の比較',
    # 8. Japanese with kagi-kakko brackets
    "「Python」と「Rust」の比較",
    # 9. Japanese with nijukagi-kakko
    "『Python』と『Rust』の比較",
    # 10. Japanese with sumitsuki-kakko
    "【Python】と【Rust】の比較",
    # 11. Japanese brackets with vs
    "「Python」 vs 「Rust」",
    "「Python」vs「Rust」",
    # 12. Japanese with fullwidth punctuation
    "ＰｙｔｈｏｎとＲｕｓｔの比較", # Fullwidth Latin
    "Python　と　Rust　の比較", # Ideographic space U+3000
    # 13. Mixed quotes and operators
    'site:zenn.dev 「Python」と「Rust」の比較',
    'site:qiita.com "FastAPI" と "Django" の比較',
]

print("=== STEP-BY-STEP TRACE IN QUERY PROCESSOR ===")
for q in queries:
    orig = q.strip()
    norm = unicodedata.normalize("NFKC", orig)
    norm_quotes = re.sub(r"[\u201c\u201d\u201e\u201f\u2033\u2036\uff02«»“”″]", '"', norm)
    norm_single = re.sub(r"[\u2018\u2019\u201a\u201b\u2032\u2035\uff07‘’′]", "'", norm_quotes)
    norm_dash = re.sub(r"[\u2013\u2014\u2015\u2212\uff0d–—]", "-", norm_single)
    norm_ws = re.sub(r"[ \t\u3000]+", " ", norm_dash).strip()
    
    pq = QueryProcessor.parse_and_normalize(q)
    
    print(f"RAW INPUT   : {q}")
    print(f"  NFKC      : {norm}")
    print(f"  NORMALIZED: {pq.normalized}")
    print(f"  CLEAN_TEXT: {pq.clean_text}")
    print(f"  NO_QUOTES : {pq.clean_no_quotes}")
    print(f"  PHRASES   : {pq.exact_phrases}")
    print(f"  INTENT    : {pq.intent}")
    print("-" * 60)
