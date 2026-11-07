import { useState } from "../../vendor/react.js";
import { api } from "../lib/api.js";
import { parseJobKey } from "../lib/jobDisplay.js";
import { html } from "../lib/html.js";
import { useResource } from "../hooks/useResource.js";

/** @param {{ jobKey: string, onRequestPasteJD: () => void }} props */
export function JDAccordion({ jobKey, onRequestPasteJD }) {
  const [expanded, setExpanded] = useState(false);
  const parsed = useResource(() => api.get("/job-parsed", { params: parseJobKey(jobKey) }), {
    deps: [jobKey],
    enabled: expanded,
  });

  const notYetParsed = parsed.error?.status === 404;

  return html`
    <div className="jd-accordion">
      <button type="button" className="jd-accordion-trigger" aria-expanded=${expanded} onClick=${() => setExpanded((v) => !v)}>
        Job description ${expanded ? "▲" : "▼"}
      </button>
      ${expanded &&
      html`<div className="jd-accordion-content">
        ${parsed.isLoading && html`<p>Loading…</p>`}
        ${notYetParsed &&
        html`<div>
          <p>Not yet parsed — run analysis first, or paste the JD manually.</p>
          <button type="button" onClick=${onRequestPasteJD}>Paste JD</button>
        </div>`}
        ${parsed.error && !notYetParsed && html`<p>Failed to load job description.</p>`}
        ${parsed.data && html`<pre className="jd-accordion-raw mono">${JSON.stringify(parsed.data, null, 2)}</pre>`}
      </div>`}
    </div>
  `;
}
