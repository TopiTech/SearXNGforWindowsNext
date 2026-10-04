import sys
import re

sys.stdout.reconfigure(encoding="utf-8")
p1_chal = re.compile(
    r"([^\sと対]{1,50}+)\s*(と|VS|対)\s*([^\sと対の比較違いどっち]{1,50}+)\s*(?:の\s*)?(比較|違い|どっち)",
    re.IGNORECASE,
)

queries = [
    "鬼滅の刃と呪術廻戦の比較",
    "「鬼滅の刃」と「呪術廻戦」の比較",
    "呪術廻戦と鬼滅の刃の比較",
    "「呪術廻戦」と「鬼滅の刃」の比較",
    "風の谷のナウシカと天空の城ラピュタの比較",
    "「風の谷のナウシカ」と「天空の城ラピュタ」の比較",
    "VueのCompositionAPIとOptionsAPIの比較",
]

for q in queries:
    m = p1_chal.search(q)
    if m:
        print(f"MATCH   : {q} -> {m.groups()}")
    else:
        print(f"NO MATCH: {q}")
