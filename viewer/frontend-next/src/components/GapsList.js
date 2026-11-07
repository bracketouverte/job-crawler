import { html } from "../lib/html.js";

/** @param {{ gaps: string[], blockers: string[] }} props */
export function GapsList({ gaps, blockers }) {
  if (gaps.length === 0 && blockers.length === 0) return null;

  return html`
    <div className="gaps-list">
      ${blockers.length > 0 &&
      html`<div className="gaps-list-section gaps-list-blockers">
        <h4>Blockers</h4>
        <ul>${blockers.map((b, i) => html`<li key=${i}>${b}</li>`)}</ul>
      </div>`}
      ${gaps.length > 0 &&
      html`<div className="gaps-list-section">
        <h4>Gaps</h4>
        <ul>${gaps.map((g, i) => html`<li key=${i}>${g}</li>`)}</ul>
      </div>`}
    </div>
  `;
}
