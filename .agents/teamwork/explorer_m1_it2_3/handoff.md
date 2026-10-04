# Handoff Report — Explorer M1-It2-3 (Normalization & Quotation Edge Cases)

**Type**: Hard Handoff  
**Working Directory**: `c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\.agents\teamwork\explorer_m1_it2_3\`  
**Target Milestone**: Milestone 1 Iteration 2 (Backend Query Pipeline Remediation)  
**Deliverable Document**: `survey_report.md`  

---

## 1. Observation

### 1.1 Gate Failure on Unspaced Japanese Comparison Queries
- In `tools/query_pipeline.py:138`:
  ```python
  138:         re.compile(r"([^\s]{1,50}+)\s*(と|VS|対)\s*([^\s]{1,50}+)\s*(?:の\s*)?(比較|違い|どっち)", re.IGNORECASE),
  ```
- Evaluated against standard natural Japanese without spaces:
  ```python
  QueryProcessor.classify_intent("PythonとRustの比較") # Returns 'research' (Expected: 'comparison')
  QueryProcessor.classify_intent("VueとReactの違い")     # Returns 'research' (Expected: 'comparison')
  QueryProcessor.classify_intent("Mac対Windowsどっち")   # Returns 'research' (Expected: 'comparison')
  ```
- Directly caused Challenger M1-1 to reject Milestone 1 in `GATE_STATUS.md:14`:
  `Gate Result: FAIL (Challenger M1-1 REJECT: Unspaced Japanese comparison queries failed due to greedy possessive token in COMPARISON_PATTERNS[1])`

### 1.2 Unicode NFKC & Quotation Character Decomposition
Executed automated decomposition on Python 3.11.9 (`test_nfkc_quotes.py`):
- Typographic double quotes `“` (U+201C), `”` (U+201D) and guillemets `«` (U+00AB), `»` (U+00BB) are **NOT normalized** by `unicodedata.normalize("NFKC", ...)` (they return unchanged). They are mapped to `"` solely by regex in `tools/query_pipeline.py:271`.
- Fullwidth quotes `＂` (U+FF02) are normalized to `"` (U+0022) by NFKC.
- Japanese corner brackets `「` (U+300C), `」` (U+300D), `『` (U+300E), `』` (U+300F), `【` (U+3010), `】` (U+3011) are **NOT normalized** by NFKC and are **NOT altered** by `query_pipeline.py:271-277`.
- Ideographic space `\u3000` is normalized to ASCII space ` ` by NFKC and collapsed by line 277.
- In `tools/query_pipeline.py:321-324`:
  ```python
  clean_text = " ".join(clean_tokens).strip()
  clean_no_quotes = re.sub(r'"([^"]+)"', r"\1", clean_text)
  clean_no_quotes = re.sub(r"\s+", " ", clean_no_quotes).strip()
  ```
  `clean_text` preserves exact-match double quotes `"` and Japanese brackets `「...」` for search engine dispatch.
  `clean_no_quotes` strips ASCII double quotes `"` for BM25 ranking and `classify_intent()`. Single quotes `'` and Japanese brackets `「...」` remain in `clean_no_quotes`.

### 1.3 Discovery: Defect in Challenger M1-1's Proposed Regex
Challenger M1-1 proposed:
```python
re.compile(r"([^\sと対]{1,50}+)\s*(と|VS|対)\s*([^\sと対の比較違いどっち]{1,50}+)\s*(?:の\s*)?(比較|違い|どっち)", re.IGNORECASE)
```
When tested on entity names containing the particle `の` in Item B (`test_no_particle.py`):
```python
pat.search("鬼滅の刃と呪術廻戦の比較")       # MATCHES: ('鬼滅の刃', 'と', '呪術廻戦', '比較')
pat.search("呪術廻戦と鬼滅の刃の比較")       # RETURNS NONE! (FAILED!)
pat.search("「呪術廻戦」と「鬼滅の刃」の比較") # RETURNS NONE! (FAILED!)
pat.search("風の谷のナウシカと天空の城ラピュタの比較") # RETURNS NONE! (FAILED!)
pat.search("「風の谷のナウシカ」と「天空の城ラピュタ」の比較") # RETURNS NONE! (FAILED!)
```
Because Group 3 `[^\sと対の比較違いどっち]{1,50}+` excludes `の`, it stops at the `の` inside `鬼滅の刃`, expects `(比較|違い|どっち)`, encounters `刃`, and fails without backtracking due to possessive `+`.

### 1.4 Discovery: Defect on Bracketed & CJK Entities in `COMPARISON_PATTERNS[0]`
In `tools/query_pipeline.py:137`:
```python
re.compile(r"\b([a-z0-9_+#.-]{1,50}+)\s+(vs|versus|compared to)\s+([a-z0-9_+#.-]{1,50}+)\b", re.IGNORECASE)
```
Evaluated against bracketed and CJK inputs (`test_patterns.py`):
```python
QueryProcessor.classify_intent("「Python」 vs 「Rust」") # Returns 'code' (FAILED!)
QueryProcessor.classify_intent("「Python」vs「Rust」")   # Returns 'code' (FAILED!)
QueryProcessor.classify_intent("'Python' vs 'Rust'")   # Returns 'code' (FAILED!)
QueryProcessor.classify_intent("機械学習 vs 深層学習")     # Returns 'research' (FAILED!)
QueryProcessor.classify_intent("Python vs. Rust")      # Returns 'research' / 'code' (FAILED!)
```
Because `[a-z0-9_+#.-]` rejects brackets, quotes, and CJK characters, and `\s+` rejects missing spaces or dots in `vs.`.

---

## 2. Logic Chain

1. **Gate Failure Chain**:
   - `COMPARISON_PATTERNS[1]` in Iteration 1 uses `[^\s]{1,50}+` (Observation 1.1).
   - In standard Japanese orthography, queries do not contain spaces between words and particles.
   - `[^\s]{1,50}+` possessively swallows the entire unspaced string `PythonとRustの比較` (14 chars) without backtracking.
   - Group 2 `(と|VS|対)` encounters end of string and fails.
   - Therefore, `classify_intent` returns `research`, bypassing comparison query expansion.

2. **Quotation Invariant Chain**:
   - `parse_and_normalize` normalizes typographic quotes to ASCII double quotes `"` (Observation 1.2).
   - `clean_no_quotes` strips ASCII double quotes `"` so `“Python” vs “Rust”` becomes `Python vs Rust`, matching Pattern 0.
   - However, Japanese brackets `「` and `」` are NOT stripped in `clean_no_quotes` (Observation 1.2).
   - Pattern 0 token class `[a-z0-9_+#.-]` rejects `「` and `」`, so `「Python」 vs 「Rust」` fails Pattern 0 (Observation 1.4).
   - Pattern 1 requires `(?:の\s*)?(比較|違い|どっち)` at the end, so `「Python」 vs 「Rust」` also fails Pattern 1.

3. **Challenger M1-1 Defect Chain**:
   - Challenger M1-1's pattern excluded `の` in Group 3 to stop before `の比較` (Observation 1.3).
   - However, when an entity name in Item B contains `の` (e.g. `鬼滅の刃`), Group 3 terminates possessively at the internal `の`.
   - The engine expects `(?:の\s*)?(比較|違い|どっち)`, encounters `刃`, and fails.
   - Replacing Group 3's possessive quantifier with a **lazy quantifier `[^\sと対]{1,50}?`** allows it to consume internal `の` characters while neatly stopping before `の比較`.

4. **ReDoS Safety Verification Chain**:
   - The lazy quantifier in Group 3 `[^\sと対]{1,50}?` is preceded by possessive Group 1 `[^\sと対]{1,50}+` and delimited by `\s*(と|VS|対)\s*`.
   - On 20,000 non-matching characters (`'a' * 20000`), execution terminates in **4.961ms**.
   - On the query pipeline length bound (`MAX_QUERY_LENGTH = 2000`), execution terminates in **0.142ms** ($< 5\text{ms}$ ReDoS requirement satisfied).

---

## 3. Caveats

1. **Search Engine Bracket Semantics**:
   External web search engines (Google, Bing, SearXNG) treat ASCII double quotes (`"..."`) as exact-phrase operators, but treat Japanese corner brackets (`「...」`) as standard punctuation. Preserving brackets in `clean_text` does not disrupt backend search execution.
2. **Double-Nested Brackets (`『...』`)**:
   Double corner brackets `『...』` behave identically to single brackets `「...」` under the proposed regex patterns and are fully supported.
3. **No Code Written to `src/`**:
   In strict adherence to Explorer read-only guidelines, all scripts and benchmarks were executed within `.agents/teamwork/explorer_m1_it2_3/`.

---

## 4. Conclusion

**Assessment**:
The Gate Iteration 1 failure is completely understood and reproducible. Challenger M1-1's proposed regex resolves unspaced queries but introduces a critical defect for entities containing the particle `の` (`呪術廻戦と鬼滅の刃の比較`).

**Actionable Recommendations for Worker M1**:

1. **Update `COMPARISON_PATTERNS[1]` in `tools/query_pipeline.py:138`** to:
   ```python
   re.compile(
       r"([^\sと対]{1,50}+)\s*(と|VS|対)\s*([^\sと対]{1,50}?)\s*(?:の\s*)?(比較|違い|どっち)",
       re.IGNORECASE,
   )
   ```
2. **Update `COMPARISON_PATTERNS[0]` in `tools/query_pipeline.py:137`** to:
   ```python
   re.compile(
       r"(?:^|\s|[^\w])['\"「『【]?([a-z0-9_+#.\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff-]{1,50}+)['\"」』】]?\s*(?:vs\.?|versus|compared\s+to)\s*['\"「『【]?([a-z0-9_+#.\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff-]{1,50}+)['\"」』】]?(?:\s|[^\w]|$)",
       re.IGNORECASE,
   )
   ```
3. **Strip quotation/bracket characters in `QueryProcessor.expand_query` (`tools/query_pipeline.py:373`)**:
   ```python
   item_a, item_b = m.group(1).strip(), m.group(3 if len(m.groups()) >= 3 else 2).strip()
   item_a = item_a.strip('"\'「」『』【】()[]')
   item_b = item_b.strip('"\'「」『』【】()[]')
   ```
4. **Add regression tests** in `tools/test_retrieval_pipeline.py` using the 15 test cases detailed in `survey_report.md:Section 7`.

---

## 5. Verification Method

To independently verify all findings and test suites:

```powershell
# 1. Run Explorer M1-It2-3 comprehensive recommended test suite (13/13 tests pass in 0.000s)
python\python.exe .agents\teamwork\explorer_m1_it2_3\test_recommended_suite.py

# 2. Run Adversarial Stress Benchmark on refined pattern (< 5ms on 20k chars)
python\python.exe .agents\teamwork\explorer_m1_it2_3\stress_refined.py

# 3. Verify that current project unit test suites remain clean (50 tests pass)
python\python.exe tools\test_retrieval_pipeline.py

# 4. Verify existing adversarial quotation test suite (28 tests pass)
python\python.exe scratch\test_quotation_adversarial.py
```
