"""Provider registry. Ported from crawler/src/providers/index.ts."""

from providers import (
    ashby,
    bamboohr,
    greenhouse,
    icims,
    lever,
    smartrecruiters,
    teamtailor,
    workable,
    workday,
)

CRAWLER_BY_PROVIDER = {
    "ashby": ashby,
    "bamboohr": bamboohr,
    "greenhouse": greenhouse,
    "icims": icims,
    "lever": lever,
    "smartrecruiters": smartrecruiters,
    "teamtailor": teamtailor,
    "workable": workable,
    "workday": workday,
}
