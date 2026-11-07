# 03: Missing profile gives an actionable 503

**What to build:** When the profile directory is missing or wrong, scoring returns a 503 whose message names the `CAREER_OPS_DIR` setting, and the job card shows that message.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] Scoring with no profile loaded returns 503 with a message naming `CAREER_OPS_DIR`
- [ ] The job card shows that message
