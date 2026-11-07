import { useState } from "react";

import { useStartMatchRunWithJD } from "../api/hooks";
import { useUiStore } from "../stores/uiStore";
import { useToastStore } from "../stores/toastStore";
import { Modal } from "./Modal";

export function PasteJDModal() {
  const isOpen = useUiStore((s) => s.isPasteJDModalOpen);
  const setOpen = useUiStore((s) => s.setPasteJDModalOpen);
  const activePanelJobKey = useUiStore((s) => s.activePanelJobKey);
  const startMatchRunWithJD = useStartMatchRunWithJD();
  const addToast = useToastStore((s) => s.addToast);
  const [jdText, setJdText] = useState("");

  if (!isOpen) return null;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!activePanelJobKey || !jdText.trim()) return;
    const [provider, source_key, ...rest] = activePanelJobKey.split("|");
    startMatchRunWithJD.mutate(
      { provider, source_key, job_id: rest.join("|"), jd_text: jdText, mode: "claude" },
      {
        onSuccess: () => {
          addToast({ message: "Analysis queued from pasted JD.", kind: "success" });
          setJdText("");
          setOpen(false);
        },
        onError: () => addToast({ message: "Failed to submit JD.", kind: "error" }),
      },
    );
  };

  return (
    <Modal title="Paste job description" onClose={() => setOpen(false)}>
      <form onSubmit={handleSubmit}>
        <textarea
          rows={12}
          value={jdText}
          onChange={(e) => setJdText(e.target.value)}
          placeholder="Paste the full job description here…"
          aria-label="Job description text"
        />
        <div className="modal-actions">
          <button type="submit" disabled={!jdText.trim() || startMatchRunWithJD.isPending}>
            {startMatchRunWithJD.isPending ? "Submitting…" : "Analyze"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
