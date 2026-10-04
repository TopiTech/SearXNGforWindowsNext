import sys
import re
import time

sys.stdout.reconfigure(encoding="utf-8")

# What if 'の' is NOT excluded from Group 3?
pat_without_no = re.compile(
    r"([^\sと対]{1,50}+)\s*(と|VS|対)\s*([^\sと対比較違いどっち]{1,50}+)\s*(?:の\s*)?(比較|違い|どっち)",
    re.IGNORECASE,
)

queries = [
    "PythonとRustの比較",
    "PythonとRust比較",
    "VueとReactの違い",
    "Mac対Windowsどっち",
    "「Python」と「Rust」の比較",
    "鬼滅の刃と呪術廻戦の比較",
    "呪術廻戦と鬼滅の刃の比較",
    "風の谷のナウシカと天空の城ラピュタの比較",
    "「風の谷のナウシカ」と「天空の城ラピュタ」の比較",
]

for q in queries:
    m = pat_without_no.search(q)
    if m:
        print(f"MATCH: {q} -> groups: {m.groups()}")
    else:
        print(f"NO MATCH: {q}")

# Let's test ReDoS latency
t0 = time.perf_counter()
m = pat_without_no.search("a" * 20000)
t1 = time.perf_counter()
print(f"ReDoS test on 'a'*20000: {(t1 - t0)*1000:.3f} ms")
