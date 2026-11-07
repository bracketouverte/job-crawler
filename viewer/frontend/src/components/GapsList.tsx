interface Props {
  gaps: string[];
  blockers: string[];
}

export function GapsList({ gaps, blockers }: Props) {
  if (gaps.length === 0 && blockers.length === 0) return null;

  return (
    <div className="gaps-list">
      {blockers.length > 0 && (
        <div className="gaps-list-section gaps-list-blockers">
          <h4>Blockers</h4>
          <ul>
            {blockers.map((blocker, i) => (
              <li key={i}>{blocker}</li>
            ))}
          </ul>
        </div>
      )}
      {gaps.length > 0 && (
        <div className="gaps-list-section">
          <h4>Gaps</h4>
          <ul>
            {gaps.map((gap, i) => (
              <li key={i}>{gap}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
