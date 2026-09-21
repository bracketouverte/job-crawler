export function parseTitleKeywords(raw: string | undefined): string[] {
  if (!raw || raw.trim() === "") {
    return [];
  }
  return raw
    .split(",")
    .map((k) => k.trim().toLowerCase())
    .filter((k) => k.length > 0);
}

export function matchesTitleFilter(title: string | null, keywords: string[]): boolean {
  if (!title || keywords.length === 0) {
    return false;
  }
  const lower = title.toLowerCase();
  return keywords.some((k) => lower.includes(k));
}
