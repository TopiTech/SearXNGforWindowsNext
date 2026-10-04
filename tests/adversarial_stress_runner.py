#!/usr/bin/env python3
"""Adversarial stress and ReDoS test harness for QueryProcessor and COMPARISON_PATTERNS.

This harness stress-tests:
1. Pathological regex inputs (20k, 50k, 100k characters) against COMPARISON_PATTERNS.
2. Pathological inputs against QueryProcessor.classify_intent.
3. Boundary inputs against QueryProcessor.parse_and_normalize (empty, 1999, 2000, 2001, 10k, 100k).
4. High-concurrency execution (multi-threaded query processing).
5. Natural Japanese syntax without whitespace (e.g. PythonとRustの比較).
"""

from __future__ import annotations

import concurrent.futures
import json
import os
import sys
import time
from typing import Any

if hasattr(sys.stdout, "reconfigure") and getattr(sys.stdout, "encoding", "").lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure") and getattr(sys.stderr, "encoding", "").lower() != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Ensure tools directory is in sys.path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
TOOLS_DIR = os.path.join(REPO_ROOT, "tools")
if TOOLS_DIR not in sys.path:
    sys.path.insert(0, TOOLS_DIR)

from query_pipeline import QueryProcessor


def run_benchmark():
    results: dict[str, Any] = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "regex_stress": [],
        "intent_stress": [],
        "boundary_stress": [],
        "concurrency_stress": {},
        "accuracy_checks": [],
    }

    print("=" * 80)
    print("CHALLENGER M1-1: ADVERSARIAL STRESS & REDOS VERIFICATION HARNESS")
    print("=" * 80)

    pat_en = QueryProcessor.COMPARISON_PATTERNS[0]
    pat_ja = QueryProcessor.COMPARISON_PATTERNS[1]

    # -------------------------------------------------------------------------
    # SUITE 1: Pathological Regex Inputs (Direct COMPARISON_PATTERNS)
    # -------------------------------------------------------------------------
    print("\n--- SUITE 1: Direct COMPARISON_PATTERNS ReDoS Stress (20k - 100k chars) ---")

    test_lengths = [20000, 50000, 100000]

    regex_payloads = [
        ("Uniform non-matching ASCII ('a'*N)", lambda n: "a" * n),
        ("Uniform non-matching Japanese ('あ'*N)", lambda n: "あ" * n),
        ("Repetitive delimiter ('と'*N)", lambda n: "と" * n),
        ("Repetitive delimiter ('VS'*(N//2))", lambda n: "VS" * (n // 2)),
        ("Repetitive delimiter ('対'*N)", lambda n: "対" * n),
        ("Repetitive delimiter combo ('とVS対'*(N//3))", lambda n: "とVS対" * (n // 3)),
        ("Repetitive partial comparison prefix ('item と item '*(N//14))", lambda n: "item と item " * (n // 14)),
        (
            "Repetitive partial comparison prefix + 'の ' ('item と item の '*(N//17))",
            lambda n: "item と item の " * (n // 17),
        ),
        (
            "Repetitive partial prefix with non-matching suffix ('item と item '*(N//14) + 'abc')",
            lambda n: ("item と item " * (n // 14))[: n - 3] + "abc",
        ),
        (
            "Repetitive partial prefix with comparison keyword at tail ('item と item '*(N//14) + '比較')",
            lambda n: ("item と item " * (n // 14))[: n - 2] + "比較",
        ),
        (
            "Repetitive partial prefix with '違い' at tail ('item と item '*(N//14) + '違い')",
            lambda n: ("item と item " * (n // 14))[: n - 2] + "違い",
        ),
        (
            "Repetitive partial prefix with 'どっち' at tail ('item と item '*(N//14) + 'どっち')",
            lambda n: ("item と item " * (n // 14))[: n - 3] + "どっち",
        ),
        ("English partial prefix ('item vs '*(N//8))", lambda n: "item vs " * (n // 8)),
        ("English partial prefix ('item compared to '*(N//17))", lambda n: "item compared to " * (n // 17)),
        (
            "English partial prefix with tail match ('item vs '*(N//8) + 'target')",
            lambda n: ("item vs " * (n // 8))[: n - 6] + "target",
        ),
        (
            "Japanese natural text without spaces ('これは非常に長いテキストであり'*(N//16))",
            lambda n: "これは非常に長いテキストであり" * (n // 16),
        ),
        ("Japanese natural text with embedded 'と' every 45 chars", lambda n: ("あ" * 44 + "と") * (n // 45)),
        ("Japanese natural text with embedded '対' every 45 chars", lambda n: ("あ" * 44 + "対") * (n // 45)),
    ]

    for desc, gen in regex_payloads:
        for n in test_lengths:
            payload = gen(n)
            # Test Japanese pattern
            t0 = time.perf_counter()
            m_ja = pat_ja.search(payload)
            dur_ja_ms = (time.perf_counter() - t0) * 1000.0

            # Test English pattern
            t0 = time.perf_counter()
            m_en = pat_en.search(payload)
            dur_en_ms = (time.perf_counter() - t0) * 1000.0

            status = "PASS" if max(dur_ja_ms, dur_en_ms) < 50.0 else "WARN (>50ms)"
            if max(dur_ja_ms, dur_en_ms) >= 1000.0:
                status = "FAIL (REDOS DETECTED >1s)"

            results["regex_stress"].append(
                {
                    "description": desc,
                    "length": len(payload),
                    "dur_ja_ms": round(dur_ja_ms, 3),
                    "dur_en_ms": round(dur_en_ms, 3),
                    "matched_ja": bool(m_ja),
                    "matched_en": bool(m_en),
                    "status": status,
                }
            )
            print(f"[{status}] {desc:<50} | Len: {len(payload):>6} | JA: {dur_ja_ms:>7.3f}ms | EN: {dur_en_ms:>7.3f}ms")

    # -------------------------------------------------------------------------
    # SUITE 2: QueryProcessor.classify_intent Stress (Keyword pre-filter bypass)
    # -------------------------------------------------------------------------
    print("\n--- SUITE 2: QueryProcessor.classify_intent Stress (20k - 100k chars) ---")

    intent_payloads = [
        ("Long non-matching string (no keywords)", lambda n: "a" * n),
        ("Keyword '比較' at very end of long string", lambda n: "a" * (n - 2) + "比較"),
        ("Keyword 'vs' at very end of long string", lambda n: "a" * (n - 2) + "vs"),
        ("Keyword '違い' at position 0 followed by long non-match", lambda n: "違い " + "a" * (n - 3)),
        ("Repetitive keyword ' 比較 ' every 100 chars", lambda n: ("a" * 96 + " 比較 ") * (n // 100)),
        ("Repetitive keyword ' vs ' every 100 chars", lambda n: ("a" * 96 + " vs ") * (n // 100)),
        (
            "Pathological comparison-like non-match with keyword ('item と item '*(N//14) + '比較')",
            lambda n: ("item と item " * (n // 14))[: n - 2] + "比較",
        ),
        ("Code traceback keyword stress ('traceback ' + 'a'*N)", lambda n: "traceback " + "a" * (n - 10)),
        ("Research keyword stress ('architecture ' + 'a'*N)", lambda n: "architecture " + "a" * (n - 13)),
    ]

    for desc, gen in intent_payloads:
        for n in test_lengths:
            payload = gen(n)
            t0 = time.perf_counter()
            intent = QueryProcessor.classify_intent(payload)
            dur_ms = (time.perf_counter() - t0) * 1000.0

            threshold = 10.0  # 10ms threshold from dispatch
            status = "PASS" if dur_ms < threshold else "WARN (>10ms)"
            if dur_ms > 100.0:
                status = "FAIL (EXCESSIVE DURATION >100ms)"

            results["intent_stress"].append(
                {
                    "description": desc,
                    "length": len(payload),
                    "intent": intent,
                    "dur_ms": round(dur_ms, 3),
                    "status": status,
                }
            )
            print(f"[{status}] {desc:<50} | Len: {len(payload):>6} | Intent: {intent:<10} | Time: {dur_ms:>7.3f}ms")

    # -------------------------------------------------------------------------
    # SUITE 3: Boundary & Pathological Queries (parse_and_normalize)
    # -------------------------------------------------------------------------
    print("\n--- SUITE 3: Boundary & Pathological Inputs (parse_and_normalize) ---")

    boundary_cases = [
        ("Empty string", ""),
        ("Whitespace only (spaces)", "    "),
        ("Whitespace only (tabs, newlines)", "\t\n\r\t"),
        ("Ideographic fullwidth spaces", "\u3000\u3000\u3000"),
        ("Mixed whitespace", " \t \r\n \u3000 "),
        ("Exact boundary: 1999 chars", "a" * 1999),
        ("Exact boundary: 2000 chars", "a" * 2000),
        ("Exact boundary: 2001 chars", "a" * 2001),
        ("Exact boundary: 2002 chars", "a" * 2002),
        ("Super boundary: 5,000 chars", "a" * 5000),
        ("Super boundary: 10,000 chars", "a" * 10000),
        ("Super boundary: 50,000 chars", "a" * 50000),
        ("Super boundary: 100,000 chars", "a" * 100000),
        ("2000-char Japanese kanji/kana", "猫" * 2000),
        ("2001-char Japanese kanji/kana", "猫" * 2001),
        ("Unclosed quote at char 1999", '"' + "a" * 1998),
        ("Closed quote starting before and ending after 2000", '"' + "a" * 1998 + '"' + "b" * 10),
        ("Operator truncated across 2000 boundary", "a" * 1995 + " site:github.com"),
        ("Multi-byte typographic quotes at boundary", "“" + "a" * 1998 + "”" + "extra"),
        ("Many operators (500 'site:foo.com')", " ".join(["site:foo.com"] * 500)),
        ("Many exact phrases (500 '\"foo\"')", " ".join(['"foo"'] * 500)),
        ("Unicode NFKC expansion input (㌀ * 2000)", "㌀" * 2000),  # ㌀ normalizes to アパート (3 chars)
        ("Null bytes and control characters", "hello\x00world\x01\x02\x03test"),
    ]

    for desc, query_str in boundary_cases:
        t0 = time.perf_counter()
        try:
            proc = QueryProcessor.parse_and_normalize(query_str)
            dur_ms = (time.perf_counter() - t0) * 1000.0

            orig_len = len(proc.original)
            clean_len = len(proc.clean_text)
            no_quotes_len = len(proc.clean_no_quotes)

            len_ok = orig_len <= 2000
            time_ok = dur_ms < 10.0

            status = "PASS" if (len_ok and time_ok) else "WARN"
            if not len_ok:
                status = "FAIL (LEN > 2000)"

            results["boundary_stress"].append(
                {
                    "description": desc,
                    "input_length": len(query_str),
                    "orig_len": orig_len,
                    "clean_len": clean_len,
                    "no_quotes_len": no_quotes_len,
                    "dur_ms": round(dur_ms, 3),
                    "status": status,
                }
            )
            print(
                f"[{status}] {desc:<45} | InLen: {len(query_str):>6} | OutOrig: {orig_len:>4} | OutClean: {clean_len:>4} | Time: {dur_ms:>7.3f}ms"
            )
        except Exception as e:  # noqa: BLE001
            dur_ms = (time.perf_counter() - t0) * 1000.0
            results["boundary_stress"].append(
                {
                    "description": desc,
                    "input_length": len(query_str),
                    "error": str(e),
                    "dur_ms": round(dur_ms, 3),
                    "status": "FAIL (EXCEPTION)",
                }
            )
            print(f"[FAIL] {desc:<45} | EXCEPTION: {e}")

    # -------------------------------------------------------------------------
    # SUITE 4: High Concurrency & Latency Distribution Stress
    # -------------------------------------------------------------------------
    print("\n--- SUITE 4: High Concurrency & Latency Distribution Stress ---")

    queries_pool = [
        "Python vs Rust",
        "React compared to Vue",
        '"FastAPI lifespan" site:fastapi.tiangolo.com',
        "a" * 2000,
        "a" * 10000,
        "Python と Rust 比較",
        "Vue と React の違い",
        "traceback (most recent call last): line 42 ValueError",
        "architecture of distributed search engines",
        "weather in tokyo today",
    ]

    total_reqs = 2000
    num_threads = 20
    print(f"Executing {total_reqs} queries across {num_threads} concurrent threads...")

    latencies: list[float] = []
    errors: list[str] = []

    def worker_task(idx: int) -> float:
        q = queries_pool[idx % len(queries_pool)]
        t_start = time.perf_counter()
        try:
            res = QueryProcessor.parse_and_normalize(q)
            assert len(res.original) <= 2000
        except Exception as ex:  # noqa: BLE001
            errors.append(str(ex))
        t_end = time.perf_counter()
        return (t_end - t_start) * 1000.0

    t_wall_start = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(worker_task, i) for i in range(total_reqs)]
        for f in concurrent.futures.as_completed(futures):
            latencies.append(f.result())
    t_wall_total = time.perf_counter() - t_wall_start

    latencies.sort()
    min_lat = latencies[0]
    max_lat = latencies[-1]
    avg_lat = sum(latencies) / len(latencies)
    p50_lat = latencies[int(len(latencies) * 0.50)]
    p90_lat = latencies[int(len(latencies) * 0.90)]
    p95_lat = latencies[int(len(latencies) * 0.95)]
    p99_lat = latencies[int(len(latencies) * 0.99)]
    qps = total_reqs / t_wall_total

    results["concurrency_stress"] = {
        "total_requests": total_reqs,
        "num_threads": num_threads,
        "wall_time_sec": round(t_wall_total, 3),
        "qps": round(qps, 1),
        "errors_count": len(errors),
        "min_ms": round(min_lat, 3),
        "avg_ms": round(avg_lat, 3),
        "p50_ms": round(p50_lat, 3),
        "p90_ms": round(p90_lat, 3),
        "p95_ms": round(p95_lat, 3),
        "p99_ms": round(p99_lat, 3),
        "max_ms": round(max_lat, 3),
    }

    print(f"Completed {total_reqs} requests in {t_wall_total:.3f}s ({qps:.1f} QPS)")
    print(
        f"Latency: min={min_lat:.3f}ms | avg={avg_lat:.3f}ms | p50={p50_lat:.3f}ms | p95={p95_lat:.3f}ms | p99={p99_lat:.3f}ms | max={max_lat:.3f}ms"
    )
    print(f"Errors: {len(errors)}")

    # -------------------------------------------------------------------------
    # SUITE 5: Semantic Accuracy & Japanese Natural Syntax Verification
    # -------------------------------------------------------------------------
    print("\n--- SUITE 5: Semantic Accuracy & Natural Japanese Syntax ---")

    accuracy_test_cases = [
        # Natural Japanese comparison queries without spaces (STANDARD JAPANESE USAGE)
        ("PythonとRustの比較", "comparison", ["Python", "Rust"], "Natural Japanese without spaces"),
        ("VueとReactの違い", "comparison", ["Vue", "React"], "Natural Japanese without spaces"),
        ("TypeScriptとJavaScriptどっち", "comparison", ["TypeScript", "JavaScript"], "Natural Japanese without spaces"),
        ("iPhone対Android比較", "comparison", ["iPhone", "Android"], "Natural Japanese without spaces"),
        ("FastAPIとDjangoの比較", "comparison", ["FastAPI", "Django"], "Natural Japanese without spaces"),
        ("PostgreSQLとMySQLの違い", "comparison", ["PostgreSQL", "MySQL"], "Natural Japanese without spaces"),
        ("Mac対Windowsどっち", "comparison", ["Mac", "Windows"], "Natural Japanese without spaces"),
        # Artificial Japanese queries with spaces (Worker M1 tests)
        ("Python と Rust 比較", "comparison", ["Python", "Rust"], "Japanese with artificial spaces"),
        ("Vue と React の違い", "comparison", ["Vue", "React"], "Japanese with artificial spaces"),
        (
            "TypeScript と JavaScript どっち",
            "comparison",
            ["TypeScript", "JavaScript"],
            "Japanese with artificial spaces",
        ),
        ("A 対 B 比較", "comparison", ["A", "B"], "Japanese with artificial spaces"),
        # English comparisons
        ("Python vs Rust", "comparison", ["Python", "Rust"], "Standard English vs"),
        ("React compared to Vue", "comparison", ["React", "Vue"], "English compared to"),
        ("FastAPI versus Django", "comparison", ["FastAPI", "Django"], "English versus"),
        ("C++ vs Rust", "comparison", ["C++", "Rust"], "English with symbols"),
        ("Node.js vs Deno", "comparison", ["Node.js", "Deno"], "English with dot"),
        # Non-comparisons
        ("Python documentation", "code", [], "Code documentation query"),
        ("Vue tutorial", "howto", [], "Howto tutorial query"),
        ("weather in Tokyo today", "fresh", [], "Fresh weather query"),
        (
            '"FastAPI lifespan" site:fastapi.tiangolo.com',
            "code",
            ["FastAPI lifespan documentation", "FastAPI lifespan github"],
            "Quoted code phrase with operator",
        ),
        (
            '"renewable energy storage" site:nature.com',
            "research",
            [],
            "Quoted research phrase with operator",
        ),
    ]

    for query_str, expected_intent, expected_expansions, desc in accuracy_test_cases:
        proc = QueryProcessor.parse_and_normalize(query_str)
        actual_intent = proc.intent
        actual_exp = QueryProcessor.expand_query(proc, mode="deep")

        intent_match = actual_intent == expected_intent
        exp_match = True
        if expected_expansions:
            for exp_item in expected_expansions:
                if exp_item not in actual_exp:
                    exp_match = False
                    break

        status = "PASS" if (intent_match and exp_match) else "FAIL"

        results["accuracy_checks"].append(
            {
                "query": query_str,
                "description": desc,
                "expected_intent": expected_intent,
                "actual_intent": actual_intent,
                "expected_expansions": expected_expansions,
                "actual_expansions": actual_exp,
                "status": status,
            }
        )

        print(
            f"[{status}] {desc:<35} | Query: {query_str:<25} | Intent: {actual_intent} (exp {expected_intent}) | Expansions: {actual_exp}"
        )

    # Output JSON summary
    summary_path = os.path.join(REPO_ROOT, ".agents", "teamwork", "challenger_m1_1", "stress_test_results.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nSaved raw benchmark results to {summary_path}")

    return results


if __name__ == "__main__":
    run_benchmark()
