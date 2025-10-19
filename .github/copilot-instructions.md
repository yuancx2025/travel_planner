# Copilot Instructions (Repo Policy)

These rules apply to Copilot Chat/Agents/Workspace when proposing code or edits in this repository.

## 0) Default Mindset
- **Bias to minimalism.** Implement the smallest working solution (MVP) that meets the prompt.
- **Do not create new files** unless explicitly approved (see §2) or the prompt *explicitly* asks for it.
- **Prefer single-file solutions** unless the current file would exceed the limits below.
- **Small diffs first.** Propose incremental changes over large refactors.

## 1) Size & Complexity Limits
- **Max diff budget:** 80 added lines per request (unless user says “bigger change approved”).
- **Max function length:** ~60 LOC; split only when there are ≥3 distinct responsibilities.
- **Max file length target:** ~400–600 LOC. Only split when:
  - file would exceed ~600 LOC *and* separation reduces coupling, or
  - a module is clearly reusable across multiple scripts.
- **Cyclomatic complexity:** Keep functions simple; favor early returns over deep nesting.

## 2) File/Folder Creation Policy
- **Ask-before-create rule (mandatory):**
  - Before adding a new file or directory, **propose a short plan**:
    - File name(s), path(s), 1–2 lines of purpose, and how they integrate.
  - Wait for explicit approval in the chat/prompt (e.g., “approved to create X and Y”).
- No scaffolding (boilerplate folders, configs, CI, or docs) unless requested.
- No codegen of “helper” modules if equivalent logic is ≤60 LOC and only used once.

## 3) “YAGNI” Checks & Validation
- Avoid defensive code that isn’t requested or required by the immediate usage.
- Only add input validation when:
  - It blocks a known failure mode already encountered or
  - The user asks for robust CLI/API surfaces or
  - It’s legally/compliance critical (not typical here).
- **No broad try/except** that masks errors. Fail fast with a clear message.

## 4) Dependencies & Imports
- **Standard library first** (pathlib, json, argparse, datetime, hashlib, re, etc.)
- **Approved heavy dependencies for this RAG project:**
  - `langchain`, `langchain-openai`, `langchain-community` (RAG framework)
  - `chromadb` (vector store)
  - `sentence-transformers`, `transformers`, `tokenizers` (embeddings/tokenization)
  - `newspaper3k`, `feedparser`, `beautifulsoup4` (scraping)
  - `pandas` (data manipulation; avoid versions ≥2.2.0 per requirements)
  - `streamlit` (UI only), `pyyaml` (config), `tqdm` (progress)
- **Ask before adding:** New LLM providers, alternative vector DBs, additional ML frameworks, or redundant libs
- **Avoid:** Multiple embedding models in one codebase; overlapping scraping/parsing libraries

## 5) Logging, Telemetry, and I/O
- Keep logging **minimal**: `INFO` for milestones, `ERROR` for failures; no verbose debug unless asked.
- Avoid generating logs/files/artifacts unless explicitly requested.

## 6) Documentation & Comments
- Add a **1–2 line module docstring** and **short function docstrings** (Google or NumPy style).
- No long tutorials or extended prose in code comments unless asked.

## 7) Testing Policy
- If adding non-trivial logic, include **one focused pytest** test per new public function.
- Keep tests **short** (happy-path + one key edge case). No fixtures unless needed.

## 8) Performance & Data
- Favor **streaming/iterators** and **chunked processing** for large files.
- Avoid premature micro-optimizations; do not parallelize unless asked or obviously necessary.

## 9) Refactors
- Do not refactor unrelated code in the same change.
- If you believe a refactor is warranted, **propose a plan** (scope, risk, LOC estimate) and wait for approval.

## 10) Interaction Protocol (for Copilot Chat/Agents)
When responding to a task:
1. **Confirm scope** in 1–3 bullets.
2. **State diff estimate** (± lines) and whether it needs new files (usually “no”).
3. If new files are proposed, follow **Ask-before-create** (§2).
4. Provide a **minimal patch** or code block; keep it in one file unless approved otherwise.
5. Include **exact run/test instructions** if relevant.

---

## Project Conventions (Python)
- Python 3.11+. Format with **Black**, lint with **Ruff**, type-check with **mypy** (strict-ish).
- CLI tools: prefer `argparse` (simple) or `typer` only if approved.
- I/O: prefer standard `pathlib`, `csv`, `json`, `sqlite3`; ask before adding DB/ORM libs.
- For data/ETL/ML scripts:
  - Single entrypoint pattern: `main()` + small helpers in the same file.
  - Promote to a module **only** after reuse appears across ≥2 scripts.

### Minimal Script Skeleton (preferred)
```python
"""Short one-line purpose."""

from __future__ import annotations
from pathlib import Path
import argparse

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Do X minimally.")
    p.add_argument("--input", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    return p.parse_args()

def core(input_path: Path, output_path: Path) -> None:
    # minimal logic; no extra validation unless asked
    ...

def main() -> None:
    args = parse_args()
    core(args.input, args.output)

if __name__ == "__main__":
    main()
```

---

## 11) RAG & NLP Pipeline Conventions
- **Data flow:** scrape → clean → chunk → embed → index → retrieve → summarize
- **Immutable data principle:** Raw data (`data/raw/`) is append-only; processed outputs go to dated files
- **Chunking strategy:** Target 700–1000 chars for news articles; preserve sentence boundaries
- **Metadata-first retrieval:** Always filter by date/source/ticker before semantic search
- **Deduplication:** Apply at multiple stages (scraping by content_hash, retrieval by article_id)

### Prompt Engineering
- Keep prompts **factual & concise**: 1–2 bullet summaries with citations
- Always include source attribution: `(SOURCE, YYYY-MM-DD)` format
- Target bullet length: ≤20 words (map), ≤30 words (reason)
- No promotional language; neutral tone only

### Vector Store & Embeddings
- Use `text-embedding-3-small` as default (balance cost/quality)
- Chroma persistence dir: `data/vdb/chroma/`
- MMR for diversity: `lambda_mult=0.6`, `fetch_k=60`, `k_final=8`
- Auto-expand date windows when results are sparse (60d → 365d max)

### Config-Driven Design
- All hyperparameters live in `config/rag.yml` (chunk size, retrieval k, etc.)
- Feed configs in `config/feeds*.yml` (domains, limits, languages)
- No hardcoded paths; use `Path(__file__).parent` for relative lookups

## 12) Data Pipeline Best Practices
- **Streaming first:** Use generators for large JSONL files; avoid loading full datasets into memory
- **Batch processing:** Index embeddings in batches (default 1500 chunks); log progress with `tqdm`
- **Deduplication early:** Hash content during scraping to skip duplicates before storage
- **Date filtering:** Always push date filters to metadata queries (Chroma `where` clause) before retrieval
- **Minimal re-processing:** Check manifest files (`preprocessed_*_manifest.json`) to skip already-processed data

### Scraping Etiquette
- Default sleep: 0.4s per request (`per_request_sleep`)
- Respect `limit` params in feed configs (typically 10–30 articles per source)
- URL normalization: strip UTM params, fragments, and tracking codes before dedup
- Article validation: skip if `len(text) < 300` chars or `words < 80`

## 13) LLM & API Call Optimization
- **Model selection:** Default to `gpt-4o-mini` (cheap, fast) for summarization; escalate to `gpt-4o` only if quality issues
- **Token limits:** Cap `max_tokens=300` for summaries, `=80` for reasons
- **Temperature:** Always `0.0` for factual summarization (deterministic outputs)
- **Prompt compression:** Pass only title + lead + chunk (not full article) to map-reduce chains
- **Batch LLM calls:** Use `asyncio` or `ThreadPoolExecutor` for parallel document summarization (but stay within rate limits)

### Retrieval Before Generation
- Never generate without retrieval: fetch relevant chunks first, then summarize
- Use MMR to reduce redundancy across retrieved chunks
- Deduplicate bullets with Jaccard similarity (threshold=0.85) to avoid LLM repetition

## 14) RAG-Specific Testing Policy
- **Unit tests:** Focus on core logic (chunking, deduplication, metadata extraction)
- **Integration tests:** Test full pipeline segments (scrape → clean, ingest → retrieve)
- **Smoke tests:** End-to-end query → retrieval → summary (see `test_end_to_end_smoke.py`)
- **Metrics:** Use ROUGE for summary quality; manual spot-checks for citation accuracy
- **Mock external calls:** Mock OpenAI API and web scraping in tests; avoid hitting live endpoints

### Test Data
- Use small fixtures (5–10 articles) in `tests/fixtures/` for fast iteration
- Test edge cases: empty queries, no results, very long articles, missing metadata

## 15) Metadata Schema Enforcement
All scraped/processed articles MUST include these fields (enforce in `validate_row`):
- `article_id`: unique hash (content-based)
- `title`, `url_canonical`, `source_short`
- `published_at`: ISO8601 UTC string
- `language`: ISO 639-1 code (e.g., "en")
- `tickers`: list of uppercase stock symbols (empty list if none)
- `text_clean`: normalized, truncated content
- `lead`: first 2–3 sentences

Optional: `section`, `authors`, `keywords`, `content_hash`

**Validation:** Fail fast if required fields are missing or malformed (no silent defaults unless documented).

## 16) Performance & Scalability Guidelines
- **Scraping:** ≤10 articles/min (rate-limited by sleep)
- **Cleaning:** ≤1s per article (tokenization is the bottleneck)
- **Embedding:** Batch 100 chunks at once; ≤5s per batch with OpenAI API
- **Retrieval:** ≤500ms for MMR search on 10K chunks (Chroma in-memory)
- **Summarization:** ≤2s per article (map-reduce with mini model)

### When to Optimize
- Only parallelize if processing >100 articles in a single run
- Profile with `cProfile` or `line_profiler` before micro-optimizing
- Monitor OpenAI token usage; log every API call cost
