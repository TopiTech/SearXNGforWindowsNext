import sys
import re
import time

sys.stdout.reconfigure(encoding="utf-8")

# Let's test non-possessive Group 3:
# r"([^\sと対]{1,50}+)\s*(と|VS|対)\s*(.+?)\s*(?:の\s*)?(比較|違い|どっち)"
pat_lazy = re.compile(
    r"([^\sと対]{1,50}+)\s*(と|VS|対)\s*([^\s]{1,50}?)\s*(?:の\s*)?(比較|違い|どっち)",
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
    m = pat_lazy.search(q)
    if m:
        print(f"MATCH: {q} -> groups: {m.groups()}")
    else:
        print(f"NO MATCH: {q}")

# ReDoS test on pathological strings
for length in [1000, 5000, 10000, 20000]:
    t0 = time.perf_counter()
    m = pat_lazy.search("a" * length)
    t1 = time.perf_counter()
    print(f"Lazy on 'a' * {length}: {(t1 - t0)*1000:.3f} ms")

evil_prefix = ("item と " * 1000)
t0 = time.perf_counter()
m = pat_lazy.search(evil_prefix)
t1 = time.perf_counter()
print(f"Lazy on evil prefix (1000 items): {(t1 - t0)*1000:.3f} ms")
