import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

interface LocalState {
  hiddenJobs: Set<string>;
  visitedJobs: Set<string>;
  favoriteCompanies: Set<string>;
  hideJob: (key: string) => void;
  unhideJob: (key: string) => void;
  visitJob: (key: string) => void;
  toggleFavoriteCompany: (company: string) => void;
}

const SET_KEYS = new Set(["hiddenJobs", "visitedJobs", "favoriteCompanies"]);

export const useLocalStore = create<LocalState>()(
  persist(
    (set) => ({
      hiddenJobs: new Set(),
      visitedJobs: new Set(),
      favoriteCompanies: new Set(),
      hideJob: (key) => set((state) => ({ hiddenJobs: new Set(state.hiddenJobs).add(key) })),
      unhideJob: (key) =>
        set((state) => {
          const next = new Set(state.hiddenJobs);
          next.delete(key);
          return { hiddenJobs: next };
        }),
      visitJob: (key) => set((state) => ({ visitedJobs: new Set(state.visitedJobs).add(key) })),
      toggleFavoriteCompany: (company) =>
        set((state) => {
          const next = new Set(state.favoriteCompanies);
          if (next.has(company)) {
            next.delete(company);
          } else {
            next.add(company);
          }
          return { favoriteCompanies: next };
        }),
    }),
    {
      name: "job-viewer-local-store",
      storage: createJSONStorage(() => localStorage, {
        reviver: (key, value) => (SET_KEYS.has(key) ? new Set(value as string[]) : value),
        replacer: (_key, value) => (value instanceof Set ? Array.from(value) : value),
      }),
    },
  ),
);
