# Pitfalls

Hard-won lessons from past bugs. Read before changing code.

## P-001: Shared async session + concurrent coroutines = "Session is already flushing"

SQLAlchemy AsyncSession is NOT safe for concurrent use from multiple coroutines.
If you `asyncio.gather` N tasks that all call `session.flush()` on the same session,
one flush will be mid-flight when another starts, causing the error.

**Fix**: Give each concurrent coroutine its own session via `get_session()`.

## P-002: Inner sessions can't see uncommitted data from outer sessions

If session A flushes rows (visible within A) and then you open session B in a
separate transaction, B cannot see A's rows until A commits.

This silently breaks pipelines where step 1 inserts data and step 2 processes
it in a new session. Everything looks fine — no exceptions — but the inner
session just gets None back and silently skips the work.

**Fix**: Commit the outer session before spawning inner sessions that need to
read its data. Always log or surface when inner lookups return None unexpectedly.

## P-003: Don't gate processing on "new items fetched"

`if emails_fetched > 0: process()` means that if processing fails mid-run,
re-running sync will skip processing entirely because the emails are already
fetched. Unprocessed items from prior runs are silently abandoned.

**Fix**: Always attempt processing. The query already filters for unprocessed
items (`classification IS NULL`), so it's a no-op when everything is done.

## P-004: Async SQLAlchemy cannot lazy-load relationships

Accessing `email.account` or `commitment.person` in async code triggers a
synchronous DB call that fails with `MissingGreenlet`. This only manifests when
the data actually exists (e.g., after the first successful processing run).

**Fix**: Use `selectinload()` in every query that touches objects whose
relationships will be accessed. Audit all `.attribute` accesses on ORM objects
in sync helper functions called from async code.

## P-005: Always surface error counts in CLI output

If your summary dict has an `errors` field but the CLI doesn't print it,
failures are completely invisible to the user. They see "Classified: 0" and
assume nothing was there, when actually everything errored out.

**Fix**: Always print error counts when > 0. Never silently swallow failure stats.

## P-006: Resolver gate didn't check commitments

The pipeline's resolver gate condition only checked for `tasks`, `people_mentioned`,
and `project_links` — but NOT `commitments`. Emails with commitments but no tasks
or people would skip resolution entirely, silently producing 0 commitment rows.

**Fix**: Add `extraction.get("commitments")` to the gate condition. Always check
every entity type the resolver can create.

## P-007: API sync endpoint gated processing on emails_fetched (P-003 repeat)

The `/sync` POST endpoint had `if request.process and sync_result["emails_fetched"] > 0`,
repeating the exact same bug as P-003 in the API layer. If sync fetched 0 new emails
but there were unprocessed emails from prior runs, processing was skipped.

**Fix**: Only gate on `request.process`, not on `emails_fetched > 0`.

## P-008: Newly created ORM objects trigger lazy-load on relationship access

When you `session.add(MyObject(...))` and then access `my_object.relationship`,
SQLAlchemy tries to lazy-load even though the collection is logically empty.
In async code this causes `MissingGreenlet` (same root as P-004, but for new
objects rather than queried ones).

**Fix**: After creating a new ORM object, initialize related collections manually
(e.g., `existing_hashes = set()`) rather than accessing the relationship attribute.
Only access relationships on objects loaded via `selectinload()`.
