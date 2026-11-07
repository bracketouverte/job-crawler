# 08: Location matches whole words

**What to build:** The location filter matches whole words only.

**Blocked by:** None (can start immediately)

**Status:** done

- [x] "or" does not match "Toronto" or "Florence"
- [x] "Remote" in the location text still matches

## Outcome

- Location term matches whole words: the location text is split on `,` `-` `/` `(` `)` `.` and matched as a word with spaces around it. Multi-word terms ("San Francisco") work.
- Tests in `viewer/backend/tests/test_filters.py` run against in-memory SQLite. They failed before the change and pass after.
- Live check (`remote=0`): `myLoc=or` returns 27 jobs, all with "or" as a word (e.g. "Dublin OR London", "NY or SF"). No "Toronto" or "Florence" matches.
- Full viewer suite: 219 passed. Lint clean.
