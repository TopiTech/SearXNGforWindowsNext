import sys
import re

sys.stdout.reconfigure(encoding="utf-8")

# Pattern variant: Group 1 excludes \sと対 possessive, Group 3 excludes \sと対 lazy
pat_refined = re.compile(
    r"([^\sと対]{1,50}+)\s*(と|VS|対)\s*([^\sと対]{1,50}?)\s*(?:の\s*)?(比較|違い|どっち)",
    re.IGNORECASE,
)

test_cases = [
    # Basic Japanese
    "PythonとRustの比較",
    "PythonとRust比較",
    "VueとReactの違い",
    "Mac対Windowsどっち",
    "iPhone対Android比較",
    "FastAPIとDjangoの比較",

    # Japanese with spaces
    "Python と Rust の比較",
    "Vue と React の違い",

    # Japanese with brackets
    "「Python」と「Rust」の比較",
    "『Python』と『Rust』の比較",
    "【Python】と【Rust】の比較",
    "「Vue」と「React」の違い",
    "「Mac」対「Windows」どっち",
    "「iPhone」対「Android」比較",

    # Tricky Japanese with 'の' in entity names
    "鬼滅の刃と呪術廻戦の比較",
    "呪術廻戦と鬼滅の刃の比較",
    "「呪術廻戦」と「鬼滅の刃」の比較",
    "風の谷のナウシカと天空の城ラピュタの比較",
    "「風の谷のナウシカ」と「天空の城ラピュタ」の比較",
    "VueのCompositionAPIとOptionsAPIの比較",

    # Multi-term comparisons
    "AとBとCの比較",
    "PythonとRubyとGoの違い",

    # False positive checks
    "Pythonの比較関数",
    "違いがわかる男",
    "どっちつかずの態度",
    "対症療法の意味",
]

print("=== REFINED PATTERN EVALUATION ===")
for q in test_cases:
    m = pat_refined.search(q)
    if m:
        print(f"MATCH   : {q:<35} -> {m.groups()}")
    else:
        print(f"NO MATCH: {q:<35}")
