# Backend + Frontend Version Review (First push vs Second push)

## Scope
Compared:
- **First push**: commit `1127aea` (`Add Backend Frontend`)
- **Second push**: commit `31dc92a` (`upgrade Frontend and backend`)

Files reviewed:
- `bwa_backend.py`
- `bwa_frontend.py`
- `requirements.txt`

## High-level result
**Recommendation: use the _second push_ as the base for release.**

## Why second push is better
1. **More robust LLM execution path in backend**
   - Adds `safe_llm_invoke(...)` with token/cost callback logging and guarded exception handling around structured calls.
   - Router and research stages are now protected with fallback behavior instead of hard failing.

2. **Cleaner and safer frontend execution flow**
   - Stream handling avoids duplicate graph invocation in normal stream path.
   - Better saved-blog loading flow (`blogs/*/blog.md`) and reusable zip bundling at blog-folder level.

3. **Dependency update supports image workflow evolution**
   - `google.genai` added in `requirements.txt`, consistent with upgraded image pipeline assumptions.

## Trade-offs / caveats in second push
- Some advanced markdown image rendering behavior from first push was simplified.
- Research result normalization appears less explicit than first push in some paths.

These are acceptable for a first public release because the second push improves stability and operational behavior where users feel it most (generation reliability + app flow).

## Suggested release strategy
- **Release now on second push**.
- Keep a short follow-up patch list:
  1) restore richer markdown caption handling if needed,
  2) tighten research normalization/dedupe,
  3) add smoke tests for stream + save/load blog path.

## Resume readiness notes
If your goal is to showcase this project on your resume, prioritize these upgrades next:
- Add automated tests + CI to demonstrate engineering rigor.
- Add a no-key sample/demo mode so reviewers can run it instantly.
- Pin dependencies and modularize backend for long-term maintainability.
