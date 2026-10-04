import sys
import unicodedata
import re

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "tools")
from query_pipeline import QueryProcessor

test_cases = [
    # Basic comparisons
    "Python vs Rust",
    "Python と Rust 比較",
    "PythonとRustの比較",
    "VueとReactの違い",
    "Mac対Windowsどっち",
    "iPhone対Android比較",
    "FastAPIとDjangoの比較",
    
    # ASCII Quotes
    '"Python" vs "Rust"',
    '"Python" と "Rust" の比較',
    '"Python"と"Rust"の比較',
    '"Vue"と"React"の違い',

    # Fullwidth / typographic quotes
    "“Python” vs “Rust”",
    "“Python”と“Rust”の比較",
    "‘Python’と‘Rust’の比較",

    # Japanese brackets
    "「Python」と「Rust」の比較",
    "「Python」vs「Rust」",
    "「Vue」と「React」の違い",
    "『Python』と『Rust』の比較",
    "【Python】と【Rust】の比較",
    "（Python）と（Rust）の比較",
    "［Python］と［Rust］の比較",
    "〈Python〉と〈Rust〉の比較",
    "《Python》と《Rust》の比較",

    # Mixed whitespace and brackets
    "「Python」 と 「Rust」 の比較",
    " 「Python」 と 「Rust」 の比較 ",
    "『Python』 と 『Rust』 の比較",
    
    # Halfwidth kana / compatibility chars
    "ｶﾀｶﾅとﾋﾗｶﾞﾅの比較",
    "Ｃ＋＋とＲｕｓｔの比較", # Fullwidth C++ and Rust
    "C++とRustの比較",
    "C#とJavaの比較",
    "Node.jsとDenoの比較",
    "Go vs Rust",
    
    # Boundary / Edge cases
    "と",
    "VS",
    "比較",
    "の比較",
    "AとB",
    "AとBの比較",
    "A vs B",
    "A versus B",
]

print("=== UNICODE NFKC INVESTIGATION ===")
test_brackets = [
    '「Python」と「Rust」の比較',
    '『Python』と『Rust』の比較',
    '【Python】と【Rust】の比較',
    '“Python”と“Rust”の比較',
    '‘Python’と‘Rust’の比較',
    'Ｃ＋＋とＲｕｓｔの比較',
    'ｶﾀｶﾅとﾋﾗｶﾞﾅの比較',
    '«Python»と«Rust»の比較',
    '‹Python›と‹Rust›の比較',
    '„Python“と”Rust”の比較',
]
for text in test_brackets:
    norm = unicodedata.normalize("NFKC", text)
    print(f"Original: {text}")
    print(f"NFKC    : {norm}")
    print(f"Equal?  : {text == norm}")
    print("-" * 40)

print("\n=== CURRENT QUERY PROCESSOR EVALUATION ===")
for q in test_cases:
    pq = QueryProcessor.parse_and_normalize(q)
    exp = QueryProcessor.expand_query(pq, mode="deep")
    print(f"Query: {q!r}")
    print(f"  norm: {pq.normalized!r}")
    print(f"  clean_text: {pq.clean_text!r}")
    print(f"  clean_no_quotes: {pq.clean_no_quotes!r}")
    print(f"  exact_phrases: {pq.exact_phrases!r}")
    print(f"  intent: {pq.intent!r}")
    print(f"  expansions: {exp!r}")

