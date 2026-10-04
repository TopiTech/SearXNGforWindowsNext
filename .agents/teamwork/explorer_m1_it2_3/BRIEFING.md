# BRIEFING — 2026-10-04T00:40:00Z

## Mission
Investigate Unicode NFKC normalization and quotation edge cases (including Japanese brackets) in comparison queries, recommending concrete test cases and regex refinements.

## 🔒 My Identity
- Archetype: explorer
- Roles: explorer, investigation, synthesis
- Working directory: c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\.agents\teamwork\explorer_m1_it2_3
- Original parent: 2da8fdd6-dc63-4790-a432-5c307d090996
- Milestone: Milestone 1 Iteration 2

## 🔒 Key Constraints
- Read-only investigation — do NOT implement code in src/
- Only write within c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\.agents\teamwork\explorer_m1_it2_3\
- Synthesize findings into survey_report.md and handoff.md

## Current Parent
- Conversation ID: 2da8fdd6-dc63-4790-a432-5c307d090996
- Updated: 2026-10-04T00:40:00Z

## Investigation State
- **Explored paths**:
  - `tools/query_pipeline.py` (NFKC, quote regex, `COMPARISON_PATTERNS`, `parse_and_normalize`, `classify_intent`, `expand_query`)
  - `tools/retrieval_service.py` (search dispatch, BM25 ranking query)
  - `tools/lexical_rerank.py` (MultilingualTokenizer, exact phrase bonuses)
  - `tests/adversarial_stress_runner.py` (Adversarial stress benchmarks)
  - `scratch/test_quotation_adversarial.py` (28 quote edge tests)
- **Key findings**:
  1. Unicode NFKC does NOT normalize typographic quotes (`“”`) or Japanese corner brackets (`「」`, `『』`, `【】`).
  2. Typographic double quotes are normalized to ASCII `"` by line 271 of `query_pipeline.py`; Japanese brackets remain intact in `clean_text` and `clean_no_quotes`.
  3. Challenger M1-1's proposed regex resolves unspaced Japanese queries but breaks whenever Item B contains the particle `の` (`呪術廻戦と鬼滅の刃の比較`).
  4. Formulated and benchmarked refined pattern using lazy quantifier `[^\sと対]{1,50}?` which resolves all unspaced, bracketed, and `の`-containing entities while maintaining ReDoS bounds (<5ms).
  5. Refined `COMPARISON_PATTERNS[0]` to support bracketed and CJK entities in `vs` queries (`「Python」 vs 「Rust」`, `機械学習 vs 深層学習`).
- **Unexplored areas**: None within the scope of normalization and quotation edge cases.

## Key Decisions Made
- Recommending Worker M1 adopt lazy quantifier `[^\sと対]{1,50}?` in Pattern 1 and relaxed token classes in Pattern 0.
- Recommending stripping surrounding brackets in `expand_query` for clean entity expansions.

## Artifact Index
- `DISPATCH.md` — Task assignment and instructions
- `BRIEFING.md` — Situational awareness and state
- `progress.md` — Liveness heartbeat and progress tracking
- `survey_report.md` — Exhaustive survey and analysis of NFKC, quotation, and comparison edge cases
- `handoff.md` — 5-component hard handoff report with actionable recommendations
- `test_recommended_suite.py` — 13-case unit test suite validating the proposed regex refinements
- `stress_refined.py` — Adversarial ReDoS benchmark runner for the refined pattern
