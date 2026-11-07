import { html } from "../lib/html.js";

const DIMENSIONS = [
  { key: "core_skills", label: "Core skills" },
  { key: "relevant_experience", label: "Relevant experience" },
  { key: "target_alignment", label: "Target alignment" },
  { key: "seniority_fit", label: "Seniority fit" },
  { key: "workplace_fit", label: "Workplace fit" },
  { key: "requirements_coverage", label: "Requirements coverage" },
];

/** @param {{ analysis: any }} props */
export function Scorecard({ analysis }) {
  return html`
    <div className="scorecard">
      ${DIMENSIONS.map(({ key, label }) => {
        const value = typeof analysis[key] === "number" ? analysis[key] : null;
        return html`<div key=${key} className="scorecard-row" title=${value !== null ? `${value.toFixed(1)} / 5` : "n/a"}>
          <span className="scorecard-label">${label}</span>
          <div className="scorecard-track">
            <div className="scorecard-fill" style=${{ width: `${value !== null ? (value / 5) * 100 : 0}%` }}></div>
          </div>
          <span className="scorecard-value mono">${value !== null ? value.toFixed(1) : "—"}</span>
        </div>`;
      })}
    </div>
  `;
}
