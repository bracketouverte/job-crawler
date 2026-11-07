import { html } from "../lib/html.js";
import { jobKey } from "../lib/jobDisplay.js";
import { JobCard } from "./JobCard.js";

/**
 * Previous rows stay on screen while the next page loads (`busy` dims them),
 * so paging never flashes an empty list.
 * @param {{ jobs: any[] | undefined, isLoading: boolean, isError: boolean, busy: boolean }} props
 */
export function JobList({ jobs, isLoading, isError, busy }) {
  if (isError && !jobs) return html`<p>Failed to load jobs.</p>`;
  if (isLoading || !jobs) return html`<p>Loading jobs…</p>`;
  if (jobs.length === 0) return html`<p>No jobs match the current filters.</p>`;

  return html`
    <div className=${`job-list${busy ? " job-list-busy" : ""}`} aria-busy=${busy}>
      ${jobs.map((job) => html`<${JobCard} key=${jobKey(job)} job=${job} />`)}
    </div>
  `;
}
