# 05: One title-matching rule

**What to build:** Simple, excluded and OR-group title terms all use the same rule: word-prefix match, AND between terms, `-x` excludes, `(a,b)` is OR. Uses the storage chosen in 04.

**Blocked by:** 04

**Status:** ready-for-agent

- [ ] `engine` matches "Engineering Manager"
- [ ] `senior -principal` excludes principal-level titles under the same rule
- [ ] `(react,vue)` returns jobs matching either term
