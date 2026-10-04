import sys
import re

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "tools")
from query_pipeline import QueryProcessor

# Challenger M1-1's proposed p1
p1_chal = re.compile(
    r"([^\sと対]{1,50}+)\s*(と|VS|対)\s*([^\sと対の比較違いどっち]{1,50}+)\s*(?:の\s*)?(比較|違い|どっち)",
    re.IGNORECASE,
)

test_queries = [
    # Standard Japanese comparisons
    "PythonとRustの比較",
    "VueとReactの違い",
    "Mac対Windowsどっち",
    "iPhone対Android比較",
    "FastAPIとDjangoの比較",
    
    # Spaced Japanese comparisons
    "Python と Rust 比較",
    "Python と Rust の比較",
    "Vue と React の違い",

    # ASCII and smart quoted comparisons
    '"Python" vs "Rust"',
    '"Python"と"Rust"の比較',
    '“Python”と“Rust”の比較',
    '‘Python’と‘Rust’の比較',

    # Japanese brackets
    "「Python」と「Rust」の比較",
    "「Vue」と「React」の違い",
    "『Python』と『Rust』の比較",
    "【Python】と【Rust】の比較",
    "「Mac」対「Windows」どっち",
    "「iPhone」対「Android」比較",
    
    # Japanese brackets with spaces
    "「Python」 と 「Rust」 の比較",
    "「Python」 と 「Rust」 比較",
    "「Python」 vs 「Rust」",
    "「Python」vs「Rust」",
    
    # Technical tokens with symbols
    "C++とRustの比較",
    "C#とJavaの比較",
    "Node.jsとDenoの比較",
    "Vue.jsとReact.jsの違い",
    "ASP.NET CoreとFastAPIの比較",
    "TCPとUDPの違い",
    "x86_64とARM64の比較",
    
    # Natural Japanese questions / trailing text
    "PythonとRustの比較について",
    "PythonとRustどっちがいい？",
    "PythonとRustの違いは何ですか",
    "PythonとRustの性能比較",

    # Multiple 'と' or 'の' particles (Tricky edge cases!)
    "東京都と大阪府の比較",
    "昨日と今日の比較",
    "人とAIの比較",
    "うどんとそばの比較",
    "本当と嘘の違い",
    
    # Edge cases where 'と' is part of a word!
    "ビットコインとイーサリアムの比較",
    "ソケットとポートの違い",
    "トマトときゅうりの比較",
    "京都と奈良の比較",
    "オブジェクト指向と関数型プログラミングの比較",

    # False positives (should NOT match comparison)
    "Pythonの比較関数",
    "Rustの比較演算子",
    "比較文化学入門",
    "違いがわかる男",
    "どっちつかずの態度",
    "VS Codeの使い方",
    "対症療法の意味",
]

print("=== EVALUATION OF CHALLENGER M1-1 PATTERN ===")
for q in test_queries:
    pq = QueryProcessor.parse_and_normalize(q)
    target = pq.clean_no_quotes.lower()
    m = p1_chal.search(target)
    if m:
        groups = m.groups()
        print(f"MATCH: {q!r} -> groups: {groups}")
    else:
        print(f"NO MATCH: {q!r}")
