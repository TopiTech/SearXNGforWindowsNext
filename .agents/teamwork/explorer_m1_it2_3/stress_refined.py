import sys
import re
import time

sys.stdout.reconfigure(encoding="utf-8")

pat_refined = re.compile(
    r"([^\sと対]{1,50}+)\s*(と|VS|対)\s*([^\sと対]{1,50}?)\s*(?:の\s*)?(比較|違い|どっち)",
    re.IGNORECASE,
)

tests = [
    ("20k 'a'", "a" * 20000),
    ("50k 'a'", "a" * 50000),
    ("100k 'a'", "a" * 100000),
    ("20k 'あ'", "あ" * 20000),
    ("100k 'と'", "と" * 100000),
    ("50k 'VS'", "VS" * 50000),
    ("100k '対'", "対" * 100000),
    ("100k ('item と item ')", ("item と item " * 7142)),
    ("20k 'a' + '比較'", "a" * 19998 + "比較"),
    ("100k 'a' + '比較'", "a" * 99998 + "比較"),
    ("20k ('item と ') + '比較'", ("item と " * 2500) + "比較"),
    ("20k ('item と ') + 'item2 の比較'", ("item と " * 2500) + "item2 の比較"),
]

print("=== ADVERSARIAL STRESS BENCHMARK FOR REFINED PATTERN ===")
for name, s in tests:
    t0 = time.perf_counter()
    m = pat_refined.search(s)
    t1 = time.perf_counter()
    latency_ms = (t1 - t0) * 1000
    print(f"{name:<35}: {latency_ms:>8.3f} ms (match={bool(m)})")
