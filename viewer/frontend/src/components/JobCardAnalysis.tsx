import type { Analysis } from "../types";

const DIMENSIONS: Array<{ key: keyof Analysis; label: string }> = [
  { key: "core_skills", label: "Core skills" },
  { key: "relevant_experience", label: "Experience" },
  { key: "target_alignment", label: "Target fit" },
  { key: "seniority_fit", label: "Seniority" },
  { key: "workplace_fit", label: "Workplace" },
  { key: "requirements_coverage", label: "Requirements" },
];

function firstSentence(text: string | undefined): string | null {
  if (!text) return null;
  const match = text.match(/^[^.!?]*[.!?]/);
  return (match ? match[0] : text).trim();
}

interface Props {
  analysis: Analysis;
}

export function JobCardAnalysis({ analysis }: Props) {
  const tldr = firstSentence(analysis.role_summary?.tldr);
  const tools = analysis.technical_tools_mentioned ?? [];

  return (
    <div className="job-card-analysis">
      {tldr && <p className="job-card-analysis-tldr">{tldr}</p>}
      <div className="job-card-analysis-bars">
        {DIMENSIONS.map(({ key, label }) => {
          const value = typeof analysis[key] === "number" ? (analysis[key] as number) : null;
          return (
            <div key={key} className="job-card-analysis-bar" title={`${label}: ${value ?? "n/a"}`}>
              <span className="job-card-analysis-bar-label">{label}</span>
              <div className="job-card-analysis-bar-track">
                <div
                  className="job-card-analysis-bar-fill"
                  style={{ width: `${value !== null ? (value / 5) * 100 : 0}%` }}
                />
              </div>
            </div>
          );
        })}
      </div>
      {tools.length > 0 && (
        <div className="job-card-analysis-pills">
          {tools.map((tool) => (
            <span key={tool} className="pill">
              {tool}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
