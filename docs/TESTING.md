# Testing (MANDATORY)

Every code change MUST include tests. No exceptions. Run `pytest tests/ -x -q` after writing them.

- **Bug fixes**: Write a regression test that fails without the fix and passes with it.
- **New functions**: Test happy path, edge cases (empty input, None, missing keys), and error paths.
- **Refactors**: Ensure existing tests still pass; add tests for any new branches.
- **Integration points** (DB, APIs, external services): Mock them. Tests must run without postgres/ollama/anthropic.
- **Async code**: Test concurrency-sensitive paths (e.g., multiple coroutines sharing state).

Structure:
- File per module: `tests/test_<module_name>.py`
- Use `conftest.py` fixtures: `make_email()`, `make_project()`, `make_task()`
- Mock external deps with `unittest.mock` / `AsyncMock`
- Aim for: every public function has at least one test, every branch has coverage

If you can verify a behavior by writing a test, write the test. Don't just fix and hope.

## Post-Mortem (MANDATORY)

When you cause a bug, introduce a regression, or discover a mistake in your own work:
1. Fix it and write a regression test
2. **Immediately** add a new entry to `docs/PITFALLS.md` (P-NNN format) explaining what went wrong and how to avoid it
3. Do NOT wait for `focus sync` — edit the file directly as part of the fix

This is not optional. The pitfalls file is your institutional memory. Every mistake not recorded is a mistake repeated.
