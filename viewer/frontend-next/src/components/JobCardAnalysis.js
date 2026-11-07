import { html } from "../lib/html.js";

const DIMENSIONS = [
  { key: "core_skills", label: "Core skills" },
  { key: "relevant_experience", label: "Experience" },
  { key: "target_alignment", label: "Target fit" },
  { key: "seniority_fit", label: "Seniority" },
  { key: "workplace_fit", label: "Workplace" },
  { key: "requirements_coverage", label: "Requirements" },
];

/** First sentence of the summary, or null when there is none. */
export function firstSentence(text) {
  if (!text) return null;
  const match = text.match(/^[^.!?]*[.!?]/);
  return (match ? match[0] : text).trim();
}

/** @param {{ analysis: any }} props */
export function JobCardAnalysis({ analysis }) {
  const tldr = firstSentence(analysis.role_summary?.tldr);
  const tools = analysis.technical_tools_mentioned ?? [];

  return html`
    <div className="job-card-analysis">
      ${tldr && html`<p className="job-card-analysis-tldr">${tldr}</p>`}
      <div className="job-card-analysis-bars">
        ${DIMENSIONS.map(({ key, label }) => {
          const value = typeof analysis[key] === "number" ? analysis[key] : null;
          return html`<div key=${key} className="job-card-analysis-bar" title=${`${label}: ${value ?? "n/a"}`}>
            <span className="job-card-analysis-bar-label">${label}</span>
            <div className="job-card-analysis-bar-track">
              <div className="job-card-analysis-bar-fill" style=${{ width: `${value !== null ? (value / 5) * 100 : 0}%` }}></div>
            </div>
          </div>`;
        })}
      </div>
      ${tools.length > 0 &&
      html`<div className="job-card-analysis-pills">
        ${tools.map((tool) => html`<span key=${tool} className="pill">${tool}</span>`)}
      </div>`}
    </div>
  `;
}
