import { html } from "../lib/html.js";

/** @param {{ tools: string[], gaps: string[] }} props */
export function ToolMatch({ tools, gaps }) {
  if (tools.length === 0) return null;

  const gapText = gaps.map((g) => g.toLowerCase());
  return html`
    <div className="tool-match">
      ${tools.map((tool) => {
        const isGap = gapText.some((gap) => gap.includes(tool.toLowerCase()));
        return html`<span key=${tool} className=${`pill tool-match-pill${isGap ? " tool-match-gap" : " tool-match-hit"}`}>
          ${tool}
        </span>`;
      })}
    </div>
  `;
}
