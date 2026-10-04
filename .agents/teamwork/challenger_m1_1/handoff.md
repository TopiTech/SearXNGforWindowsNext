# Handoff Report — Challenger M1-1 (Adversarial ReDoS & Input Stress Verifier)

**Verdict**: **REJECT** (Critical functional regression discovered in `tools/query_pipeline.py:138`)

---

## 1. Observation

### 1.1 Empirical ReDoS & Performance Benchmarking (Pass)
Using our adversarial harness `tests/adversarial_stress_runner.py` on Python 3.11.9 (`python\python.exe`):
- **Direct Regex Search on 20,000 non-matching characters (`'a' * 20000`)**:
  - Unfixed baseline: **4.296s** (catastrophic backtracking $O(N^2)$).
  - Remediated pattern (`QueryProcessor.COMPARISON_PATTERNS[1]`): **4.780ms** (linear scan $O(N)$, $< 5\text{ms}$).
- **Extreme Length Direct Regex Search (50k & 100k characters)**:
  - 50,000 chars: **11.285ms**
  - 100,000 chars: **24.124ms**
  - Repetitive delimiter strings (`'と' * 100000`, `'VS' * 50000`, `'対' * 100000`): **0.003ms – 0.004ms**.
  - Repetitive partial match prefix (`('item と item ' * 7142)` - 100k chars): **8.266ms**.
- **QueryProcessor.classify_intent Latency**:
  - 20,000 chars non-matching: **0.412ms**.
  - 20,000 chars with comparison keyword at tail (`'a' * 19998 + '比較'`): **4.976ms**.
  - 100,000 chars with comparison keyword at tail: **25.624ms**.
- **Boundary Query Handling (`QueryProcessor.parse_and_normalize`)**:
  - Empty string `""`: **0.015ms**, `orig_len = 0`, `clean_len = 0`.
  - Whitespace-only (`"    "`, `"\t\n\r"`, ideographic `\u3000\u3000`): **0.002ms**, `orig_len = 0`, `clean_len = 0`.
  - Exact boundary 2,000 chars: **0.213ms**, `orig_len = 2000`, `clean_len = 2000`.
  - Exact boundary 2,001 chars: **0.205ms**, `orig_len = 2000` (strictly truncated to `MAX_QUERY_LENGTH`).
  - Extreme inputs (5,000 / 10,000 / 50,000 / 100,000 chars): **0.201ms**, truncated to 2,000 chars without uncaught exceptions.
- **High Concurrency & Latency Distribution**:
  - 2,000 requests executed across 20 concurrent worker threads:
  - Total elapsed wall time: **0.094s** (**21,315.0 QPS**).
  - Latencies: min = **0.007ms**, avg = **0.057ms**, p50 = **0.012ms**, p95 = **0.112ms**, p99 = **0.166ms**, max = **31.672ms**.
  - Total errors: **0**.

### 1.2 Critical Defect: Regression on Natural Japanese Comparison Queries (Fail)
In `tools/query_pipeline.py:138`:
```python
136:     COMPARISON_PATTERNS: ClassVar[list[re.Pattern]] = [
137:         re.compile(r"\b([a-z0-9_+#.-]{1,50}+)\s+(vs|versus|compared to)\s+([a-z0-9_+#.-]{1,50}+)\b", re.IGNORECASE),
138:         re.compile(r"([^\s]{1,50}+)\s*(と|VS|対)\s*([^\s]{1,50}+)\s*(?:の\s*)?(比較|違い|どっち)", re.IGNORECASE),
139:     ]
```

When evaluated against natural Japanese comparison queries written according to standard Japanese orthography (without whitespace between words and grammatical particles):
```python
# Direct execution:
QueryProcessor.COMPARISON_PATTERNS[1].search("PythonとRustの比較")  # Returns None
QueryProcessor.COMPARISON_PATTERNS[1].search("VueとReactの違い")      # Returns None
QueryProcessor.COMPARISON_PATTERNS[1].search("TypeScriptとJavaScriptどっち") # Returns None
QueryProcessor.COMPARISON_PATTERNS[1].search("iPhone対Android比較")  # Returns None
QueryProcessor.COMPARISON_PATTERNS[1].search("FastAPIとDjangoの比較") # Returns None
```

Empirical results from `QueryProcessor.classify_intent()` and `QueryProcessor.expand_query()`:
- `QueryProcessor.classify_intent("PythonとRustの比較")`:
  - Expected: `"comparison"`
  - Actual: `"research"`
- `QueryProcessor.expand_query(proc, mode="deep")`:
  - Expected: `["Python", "Rust"]`
  - Actual: `["PythonとRustの比較 architecture"]`
- `QueryProcessor.classify_intent("VueとReactの違い")`:
  - Expected: `"comparison"`
  - Actual: `"research"`
- `QueryProcessor.classify_intent("Mac対Windowsどっち")`:
  - Expected: `"comparison"`
  - Actual: `"research"`

Worker M1's regression tests in `tools/test_retrieval_pipeline.py:821-837` did not catch this because they only tested queries with artificially inserted spaces around Japanese particles (`"Python と Rust 比較"`, `"Vue と React の違い"`).

---

## 2. Logic Chain

1. **Root Cause Analysis of the Regression**:
   - In `tools/query_pipeline.py:138`, pattern 1 was defined as:
     `r"([^\s]{1,50}+)\s*(と|VS|対)\s*([^\s]{1,50}+)\s*(?:の\s*)?(比較|違い|どっち)"`
   - Group 1 uses the token matcher `[^\s]{1,50}+` with a possessive quantifier (`+`).
   - In standard Japanese writing, queries like `"PythonとRustの比較"` contain zero whitespace characters. Every character in the string satisfies `[^\s]`.
   - When the regex engine evaluates `"PythonとRustの比較"` (length 14 $\le 50$), group 1 greedily matches all 14 characters possessively (`+`).
   - Possessive quantifiers never relinquish matched characters via backtracking.
   - When the regex engine advances to group 2 `(と|VS|対)`, the input string has already been completely consumed. Group 2 fails.
   - The regex engine then attempts matches starting at subsequent positions (1, 2, ..., 13), each of which similarly swallows all remaining non-whitespace characters and fails group 2.
   - Consequently, `search()` returns `None`.

2. **Downstream Pipeline Impact**:
   - In `QueryProcessor.classify_intent` (line 212):
     Although `"比較"` or `"違い"` is detected by `COMPARISON_KEYWORDS`, `pat.search(low)` returns `None`.
     The query drops through to later intent branches and is misclassified as `"research"` (or `"code"`).
   - In `QueryProcessor.expand_query` (line 368):
     Because `processed.intent != "comparison"`, comparative query expansion is bypassed completely. Users searching for product or technology comparisons receive irrelevant generic query expansions like `"PythonとRustの比較 architecture"`.

3. **Empirical Validation of the Proposed Remediated Pattern**:
   To preserve both ReDoS safety AND correct parsing of natural unspaced Japanese text, the character classes must explicitly exclude the delimiters:
   ```python
   re.compile(
       r"([^\sと対]{1,50}+)\s*(と|VS|対)\s*([^\sと対の比較違いどっち]{1,50}+)\s*(?:の\s*)?(比較|違い|どっち)",
       re.IGNORECASE,
   )
   ```
   We verified this pattern empirically:
   - Natural Japanese without spaces:
     - `"PythonとRustの比較"` $\rightarrow$ matches groups `('Python', 'と', 'Rust', '比較')`
     - `"VueとReactの違い"` $\rightarrow$ matches groups `('Vue', 'と', 'React', '違い')`
     - `"MacとWindowsどっち"` $\rightarrow$ matches groups `('Mac', 'と', 'Windows', 'どっち')`
     - `"iPhone対Android比較"` $\rightarrow$ matches groups `('iPhone', '対', 'Android', '比較')`
   - Japanese with spaces:
     - `"Python と Rust の比較"` $\rightarrow$ matches groups `('Python', 'と', 'Rust', '比較')`
     - `"Vue と React の違い"` $\rightarrow$ matches groups `('Vue', 'と', 'React', '違い')`
   - ReDoS Safety on 20,000 – 100,000 characters:
     - Uniform non-matching (`'a' * 20000`): **4.540ms** ($< 5\text{ms}$)
     - Repetitive partial match prefix (`('item と item ' * 1428)`): **1.295ms**
     - Uniform non-matching (`'a' * 100000`): **24.275ms**

---

## 3. Caveats

1. **NFKC Unicode Expansion**:
   `unicodedata.normalize("NFKC", orig)` is executed after truncating `orig` to `MAX_QUERY_LENGTH = 2000`. Compatibility composite characters (such as `㌀`, U+3300 SQUARE APAATO, which expands to `アパート` - 4 characters) can result in `clean_text` exceeding 2,000 characters (e.g., 2,000 `㌀` expands to 8,000 characters). This does not crash or exceed time limits (2.63ms), but is noted as a boundary characteristic.
2. **Review-Only Constraint**:
   As Challenger, we are strictly review-only and did not alter `tools/query_pipeline.py`. Worker M1 must apply the regex update and corresponding regression tests.

---

## 4. Conclusion

**Verdict: REJECT**

While Worker M1 successfully addressed the ReDoS vulnerability on English patterns and established the `MAX_QUERY_LENGTH = 2000` boundary guard, the remediation for `COMPARISON_PATTERNS[1]` introduced a critical functional defect that breaks comparative search parsing for natural Japanese text.

**Required Action Items for Worker M1**:
1. Update `COMPARISON_PATTERNS[1]` in `tools/query_pipeline.py:138` to:
   ```python
   re.compile(
       r"([^\sと対]{1,50}+)\s*(と|VS|対)\s*([^\sと対の比較違いどっち]{1,50}+)\s*(?:の\s*)?(比較|違い|どっち)",
       re.IGNORECASE,
   )
   ```
2. In `tools/test_retrieval_pipeline.py`, add regression test cases for natural Japanese queries without spaces:
   - `"PythonとRustの比較"`
   - `"VueとReactの違い"`
   - `"TypeScriptとJavaScriptどっち"`
   - `"iPhone対Android比較"`
   - `"FastAPIとDjangoの比較"`
3. Verify that all 50 unit tests and the evaluation benchmark pass cleanly.

---

## 5. Verification Method

To independently reproduce and verify this finding:

```powershell
# 1. Reproduce the bug on current codebase (Demonstrates failure to match)
python\python.exe -c "import sys; sys.path.insert(0, 'tools'); from query_pipeline import QueryProcessor; print('Intent for PythonとRustの比較:', QueryProcessor.classify_intent('PythonとRustの比較'))"
# Output on unfixed code: 'research' (EXPECTED: 'comparison')

# 2. Run the full adversarial stress harness
python\python.exe tests/adversarial_stress_runner.py

# 3. Verify the proposed remediated pattern
python\python.exe -c "import re; pat = re.compile(r'([^\sと対]{1,50}+)\s*(と|VS|対)\s*([^\sと対の比較違いどっち]{1,50}+)\s*(?:の\s*)?(比較|違い|どっち)', re.IGNORECASE); print(pat.search('PythonとRustの比較').groups()); print(pat.search('VueとReactの違い').groups())"
# Output: ('Python', 'と', 'Rust', '比較'), ('Vue', 'と', 'React', '違い')
```
