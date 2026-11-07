import { useEffect, useState } from "../../vendor/react.js";
import { readLocalState, writeLocalState } from "../lib/localStore.js";

/** Hidden, visited and favourite marks, persisted to localStorage on every change. */
export function useLocalState() {
  const [sets, setSets] = useState(() => readLocalState(window.localStorage));

  useEffect(() => {
    writeLocalState(window.localStorage, sets);
  }, [sets]);

  const update = (field, fn) => setSets((s) => ({ ...s, [field]: fn(new Set(s[field])) }));

  return {
    hiddenJobs: sets.hiddenJobs,
    visitedJobs: sets.visitedJobs,
    favoriteCompanies: sets.favoriteCompanies,
    hideJob: (key) => update("hiddenJobs", (set) => set.add(key)),
    unhideJob: (key) =>
      update("hiddenJobs", (set) => {
        set.delete(key);
        return set;
      }),
    visitJob: (key) => update("visitedJobs", (set) => set.add(key)),
    toggleFavoriteCompany: (company) =>
      update("favoriteCompanies", (set) => {
        if (set.has(company)) set.delete(company);
        else set.add(company);
        return set;
      }),
  };
}
