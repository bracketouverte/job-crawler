### Ashby

```bash

curl -sS 'https://jobs.ashbyhq.com/api/non-user-graphql?op=ApiJobBoardWithTeams' \
-H 'Content-Type: application/json' \
-H 'Origin: https://jobs.ashbyhq.com' \
-H 'Referer: https://jobs.ashbyhq.com/{company}' \
-H 'apollographql-client-name: frontend_non_user' \
-H 'apollographql-client-version: 0.1.0' \
 --data '{"operationName":"ApiJobBoardWithTeams","variables":{"organizationHostedJobsPageName":"{company}"},"query":"query ApiJobBoardWithTeams($organizationHostedJobsPageName: String!) { jobBoard: jobBoardWithTeams(organizationHostedJobsPageName: $organizationHostedJobsPageName) { jobPostings { id title locationName employmentType compensationTierSummary } } }"}'
```

### BambooHR

```bash
https://{company}.bamboohr.com/careers/list
https://{company}.bamboohr.com/careers/{job_id}/detail
```

### Lever

```bash
https://api.lever.co/v0/postings/{company}?mode=json
```
### Teamtailor

```bash
https://{company}.teamtailor.com/jobs.rss
```

### Workday
```bash
curl -sS 'https://{company}.{shard}.myworkdayjobs.com/wday/cxs/{company}/{site}/jobs' \
  -H 'Accept: application/json' \
  -H 'Content-Type: application/json' \
  --data '{"appliedFacets":{},"limit":20,"offset":0,"searchText":""}'
```