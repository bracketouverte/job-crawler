import { create } from "zustand";

interface UiState {
  activePanelJobKey: string | null;
  isQueueDrawerOpen: boolean;
  isPasteJDModalOpen: boolean;
  isFavoritesModalOpen: boolean;
  activePollIds: Set<string>;
  analysisSpinnerKeys: Set<string>;
  setActivePanelJobKey: (key: string | null) => void;
  setQueueDrawerOpen: (open: boolean) => void;
  setPasteJDModalOpen: (open: boolean) => void;
  setFavoritesModalOpen: (open: boolean) => void;
  addActivePollId: (id: string) => void;
  removeActivePollId: (id: string) => void;
  addAnalysisSpinnerKey: (key: string) => void;
  removeAnalysisSpinnerKey: (key: string) => void;
}

export const useUiStore = create<UiState>((set) => ({
  activePanelJobKey: null,
  isQueueDrawerOpen: false,
  isPasteJDModalOpen: false,
  isFavoritesModalOpen: false,
  activePollIds: new Set(),
  analysisSpinnerKeys: new Set(),
  setActivePanelJobKey: (key) => set({ activePanelJobKey: key }),
  setQueueDrawerOpen: (open) => set({ isQueueDrawerOpen: open }),
  setPasteJDModalOpen: (open) => set({ isPasteJDModalOpen: open }),
  setFavoritesModalOpen: (open) => set({ isFavoritesModalOpen: open }),
  addActivePollId: (id) =>
    set((state) => ({ activePollIds: new Set(state.activePollIds).add(id) })),
  removeActivePollId: (id) =>
    set((state) => {
      const next = new Set(state.activePollIds);
      next.delete(id);
      return { activePollIds: next };
    }),
  addAnalysisSpinnerKey: (key) =>
    set((state) => ({ analysisSpinnerKeys: new Set(state.analysisSpinnerKeys).add(key) })),
  removeAnalysisSpinnerKey: (key) =>
    set((state) => {
      const next = new Set(state.analysisSpinnerKeys);
      next.delete(key);
      return { analysisSpinnerKeys: next };
    }),
}));
