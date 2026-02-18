# AI Blog Engine

A LangGraph-based multi-agent application that plans, researches, writes, and packages technical blog posts with optional generated images.


## Current architecture

### Backend (`bwa_backend.py`)
- Uses a typed shared state for graph execution.
- Chooses mode (`closed_book` / `hybrid` / `open_book`) in a router node.
- Runs Tavily-backed research when needed.
- Builds a writing plan, fan-outs section tasks, merges content, and runs an image placement/generation pass.

### Frontend (`bwa_frontend.py`)
- Streamlit UI to submit topic + date.
- Streams run progress logs from graph execution.
- Shows plan/evidence/preview/images/log tabs.
- Loads previously saved blog artifacts from `blogs/*/blog.md`.
- Exports complete blog bundles as ZIP.

---

## Quickstart

### 1) Install dependencies
```bash
pip install -r requirements.txt
```

### 2) Configure environment
Create a `.env` file with keys as needed:
```env
OPENAI_API_KEY=...
TAVILY_API_KEY=...   # optional but recommended for research mode
```

### 3) Run the app
```bash
streamlit run bwa_frontend.py
```

---

## Recommended upgrades before adding to resume

These are the highest ROI improvements to make this look “production-ready” to recruiters/hiring managers.

### Priority 1 — Testing & quality gates
- Add **unit tests** for:
  - `safe_slug`, zip bundling, markdown image parsing.
  - router fallback behavior and research fallbacks.
- Add **integration smoke test** for one full graph run using mocked LLM calls.
- Add a small CI workflow (lint + tests) so your repo shows automated quality checks.

### Priority 2 — Observability and reliability
- Persist run metadata (`mode`, token usage, duration, errors) to a lightweight log file.
- Add explicit retry/backoff policy for network/LLM/tool failures.
- Add timeout controls per graph stage to avoid hanging runs.

### Priority 3 — Product polish
- Add an in-app **“Sample Run”** mode (no API keys required) for portfolio reviewers.
- Add richer markdown rendering/caption support for generated images.
- Add “copy blog markdown” and “download evidence CSV” actions.

### Priority 4 — Engineering maturity
- Add `pre-commit` with formatting + import sorting + linting.
- Pin dependency versions in `requirements.txt` for reproducibility.
- Split backend into modules (`schemas.py`, `nodes.py`, `image_pipeline.py`, `graph.py`) for maintainability.

---

## Resume-ready bullet examples

You can adapt these bullets directly:
- Built a **multi-agent technical writing system** using LangGraph, combining routing, retrieval, structured planning, and parallel section generation.
- Designed **typed LLM contracts** (Pydantic) to improve reliability and reduce malformed outputs in production flows.
- Implemented a Streamlit product interface with **run-time trace visibility**, historical artifact loading, and one-click blog bundle export.
- Added failure-safe orchestration patterns (fallback paths + guarded tool calls) to improve robustness under API/tool errors.

---

## Repo files
- `bwa_backend.py` — Graph pipeline and node logic.
- `bwa_frontend.py` — Streamlit app and rendering logic.
- `VERSION_REVIEW.md` — First-push vs second-push release recommendation.
