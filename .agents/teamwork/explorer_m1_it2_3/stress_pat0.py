import sys
import re
import time

sys.stdout.reconfigure(encoding="utf-8")

pat0_refined = re.compile(
    r"""
    (?:^|\s|[^\w])
    ['"「『【]?
    ([a-z0-9_+#.\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff-]{1,50}+)
    ['"」』】]?
    \s*(?:vs\.?|versus|compared\s+to)\s*
    ['"「『【]?
    ([a-z0-9_+#.\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff-]{1,50}+)
    ['"」』】]?
    (?:\s|[^\w]|$)
    """,
    re.IGNORECASE | re.VERBOSE,
)

tests = [
    ("20k 'a'", "a" * 20000),
    ("50k 'a'", "a" * 50000),
    ("100k 'a'", "a" * 100000),
    ("20k 'あ'", "あ" * 20000),
    ("50k 'vs'", "vs" * 50000),
    ("20k ('item vs ') + 'item2'", ("item vs " * 2500) + "item2"),
]

print("=== PAT0 REFINED STRESS TEST ===")
for name, s in tests:
    t0 = time.perf_counter()
    m = pat0_refined.search(s)
    t1 = time.perf_counter()
    print(f"{name:<35}: {(t1 - t0)*1000:>8.3f} ms (match={bool(m)})")
