interface Props {
  tools: string[];
  gaps: string[];
}

export function ToolMatch({ tools, gaps }: Props) {
  if (tools.length === 0) return null;

  const gapSet = new Set(gaps.map((g) => g.toLowerCase()));

  return (
    <div className="tool-match">
      {tools.map((tool) => {
        const isGap = [...gapSet].some((gap) => gap.includes(tool.toLowerCase()));
        return (
          <span key={tool} className={`pill tool-match-pill${isGap ? " tool-match-gap" : " tool-match-hit"}`}>
            {tool}
          </span>
        );
      })}
    </div>
  );
}
