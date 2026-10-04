import sys
import re
import time

sys.stdout.reconfigure(encoding="utf-8")

pat_lazy = re.compile(
    r"([^\sと対]{1,50}+)\s*(と|VS|対)\s*([^\s]{1,50}?)\s*(?:の\s*)?(比較|違い|どっち)",
    re.IGNORECASE,
)

# Test 1: repeated delimiters with comparison at tail
for n in [100, 500, 1000, 5000]:
    s = ("item と " * n) + "比較"
    t0 = time.perf_counter()
    m = pat_lazy.search(s)
    t1 = time.perf_counter()
    print(f"Repeated 'item と ' * {n} + '比較': {(t1 - t0)*1000:.3f} ms, Match: {bool(m)}")

# Test 2: repeated delimiters WITHOUT comparison at tail
for n in [100, 500, 1000, 5000]:
    s = ("item と " * n) + "nomatch"
    t0 = time.perf_counter()
    m = pat_lazy.search(s)
    t1 = time.perf_counter()
    print(f"Repeated 'item と ' * {n} + 'nomatch': {(t1 - t0)*1000:.3f} ms, Match: {bool(m)}")

# Test 3: non-matching Japanese without spaces
for n in [1000, 5000, 10000, 20000]:
    s = "あ" * n
    t0 = time.perf_counter()
    m = pat_lazy.search(s)
    t1 = time.perf_counter()
    print(f"Japanese 'あ' * {n}: {(t1 - t0)*1000:.3f} ms, Match: {bool(m)}")

# Test 4: Japanese repeated 'と' without comparison
for n in [1000, 5000, 10000, 20000]:
    s = "と" * n
    t0 = time.perf_counter()
    m = pat_lazy.search(s)
    t1 = time.perf_counter()
    print(f"Repeated 'と' * {n}: {(t1 - t0)*1000:.3f} ms, Match: {bool(m)}")
