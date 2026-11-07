import type { Analysis } from "../types";

const DIMENSIONS: Array<{ key: keyof Analysis; label: string }> = [
  { key: "core_skills", label: "Core skills" },
  { key: "relevant_experience", label: "Relevant experience" },
  { key: "target_alignment", label: "Target alignment" },
  { key: "seniority_fit", label: "Seniority fit" },
  { key: "workplace_fit", label: "Workplace fit" },
  { key: "requirements_coverage", label: "Requirements coverage" },
];

interface Props {
  analysis: Analysis;
}

export function Scorecard({ analysis }: Props) {
  return (
    <div className="scorecard">
      {DIMENSIONS.map(({ key, label }) => {
        const value = typeof analysis[key] === "number" ? (analysis[key] as number) : null;
        return (
          <div key={key} className="scorecard-row" title={value !== null ? `${value.toFixed(1)} / 5` : "n/a"}>
            <span className="scorecard-label">{label}</span>
            <div className="scorecard-track">
              <div
                className="scorecard-fill"
                style={{ width: `${value !== null ? (value / 5) * 100 : 0}%` }}
              />
            </div>
            <span className="scorecard-value mono">{value !== null ? value.toFixed(1) : "—"}</span>
          </div>
        );
      })}
    </div>
  );
}
