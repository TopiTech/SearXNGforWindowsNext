import sys
import re
import time

sys.stdout.reconfigure(encoding="utf-8")

# Original baseline pattern before M1
orig_pat = re.compile(r"([^\s]+)\s*(と|VS|対)\s*([^\s]+)\s*(比較|違い|どっち)", re.IGNORECASE)

# Let's test on non-matching strings of various lengths
for length in [1000, 5000, 10000, 20000]:
    evil_str = "a" * length
    t0 = time.perf_counter()
    m = orig_pat.search(evil_str)
    t1 = time.perf_counter()
    print(f"Original on 'a' * {length}: {(t1 - t0)*1000:.3f} ms")

evil_delim = "a と " * 500
t0 = time.perf_counter()
m = orig_pat.search(evil_delim)
t1 = time.perf_counter()
print(f"Original on ('a と ' * 500): {(t1 - t0)*1000:.3f} ms")
