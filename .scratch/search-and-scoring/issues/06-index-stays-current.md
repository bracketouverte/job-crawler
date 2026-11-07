# 06: Index stays current after a crawl

**What to build:** If 04 chose FTS, newly crawled jobs appear in title search without a rebuild. Touches the crawler↔viewer SQLite contract, so the crawler side is checked.

**Blocked by:** 05

**Status:** not applicable (04 chose LIKE)

- [ ] A job inserted after startup appears in title search
- [ ] Crawler writes and the viewer's index stay consistent (coordinated with crawler)
- [x] Not applicable: 04 chose LIKE, so no index to sync
