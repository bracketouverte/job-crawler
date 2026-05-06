// Parse compensation text (e.g. "$80,000 - $120,000") into numeric min/max
export function parseCompensation(raw: string | null): { min: number | null; max: number | null } {
  if (!raw) return { min: null, max: null };

  // Clean up the string: remove currency symbols, commas, extra whitespace
  let cleaned = raw
    .replace(/[$€£¥]/g, '')
    .replace(/,/g, '')
    .toLowerCase()
    .trim();

  // Handle k/K suffix (thousands)
  const withoutK = cleaned.replace(/k\b/g, '000');

  // Try to extract numbers (handling both ranges and single values)
  const numbers: number[] = [];
  const numberRegex = /\d+(?:000)?/g;
  let match;

  while ((match = numberRegex.exec(withoutK)) !== null) {
    const num = parseInt(match[0], 10);
    if (!isNaN(num)) {
      numbers.push(num);
    }
  }

  if (numbers.length === 0) {
    return { min: null, max: null };
  }

  if (numbers.length === 1) {
    const val = numbers[0];
    return { min: val ?? null, max: val ?? null };
  }

  // Multiple numbers found — use min and max
  const sorted = numbers.sort((a, b) => a - b);
  const min = sorted[0] ?? null;
  const max = sorted[sorted.length - 1] ?? null;
  return { min, max };
}
