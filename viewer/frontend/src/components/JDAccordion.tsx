import { useState } from "react";
import { AxiosError } from "axios";

import { useJobParsed } from "../api/hooks";

interface Props {
  jobKey: string;
  onRequestPasteJD?: () => void;
}

export function JDAccordion({ jobKey, onRequestPasteJD }: Props) {
  const [expanded, setExpanded] = useState(false);
  const parsed = useJobParsed(jobKey, expanded);

  const notYetParsed = parsed.isError && (parsed.error as AxiosError)?.response?.status === 404;

  return (
    <div className="jd-accordion">
      <button
        type="button"
        className="jd-accordion-trigger"
        aria-expanded={expanded}
        onClick={() => setExpanded((v) => !v)}
      >
        Job description {expanded ? "▲" : "▼"}
      </button>
      {expanded && (
        <div className="jd-accordion-content">
          {parsed.isLoading && <p>Loading…</p>}
          {notYetParsed && (
            <div>
              <p>Not yet parsed — run analysis first, or paste the JD manually.</p>
              {onRequestPasteJD && (
                <button type="button" onClick={onRequestPasteJD}>
                  Paste JD
                </button>
              )}
            </div>
          )}
          {parsed.isError && !notYetParsed && <p>Failed to load job description.</p>}
          {parsed.data && (
            <pre className="jd-accordion-raw mono">{JSON.stringify(parsed.data, null, 2)}</pre>
          )}
        </div>
      )}
    </div>
  );
}
