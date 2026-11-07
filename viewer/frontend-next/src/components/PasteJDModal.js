import { useState } from "../../vendor/react.js";
import { api } from "../lib/api.js";
import { html } from "../lib/html.js";
import { useToast, useUi } from "../state/context.js";
import { Modal } from "./Modal.js";

export function PasteJDModal() {
  const ui = useUi();
  const { addToast } = useToast();
  const [jdText, setJdText] = useState("");
  const [submitting, setSubmitting] = useState(false);

  if (!ui.pasteOpen) return null;

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!ui.panelJobKey || !jdText.trim()) return;
    const [provider, source_key, ...rest] = ui.panelJobKey.split("|");
    setSubmitting(true);
    try {
      await api.post("/match-runs-with-jd", {
        provider,
        source_key,
        job_id: rest.join("|"),
        jd_text: jdText,
        mode: "claude",
      });
      addToast({ message: "Analysis queued from pasted JD.", kind: "success" });
      setJdText("");
      ui.setPasteOpen(false);
      ui.refreshQueue();
    } catch (error) {
      addToast({ message: `Failed to submit JD: ${error.message}`, kind: "error" });
    } finally {
      setSubmitting(false);
    }
  };

  return html`
    <${Modal} title="Paste job description" onClose=${() => ui.setPasteOpen(false)}>
      <form onSubmit=${handleSubmit}>
        <textarea
          rows=${12}
          value=${jdText}
          onChange=${(e) => setJdText(e.target.value)}
          placeholder="Paste the full job description here…"
          aria-label="Job description text"
        ></textarea>
        <div className="modal-actions">
          <button type="submit" disabled=${!jdText.trim() || submitting}>
            ${submitting ? "Submitting…" : "Analyze"}
          </button>
        </div>
      </form>
    <//>
  `;
}
