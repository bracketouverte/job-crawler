export function asString(value: unknown): string | null {
  if (typeof value === "string") {
    const trimmed = value.trim();
    return trimmed.length > 0 ? trimmed : null;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return null;
}

export function firstString(...values: unknown[]): string | null {
  for (const value of values) {
    const stringValue = asString(value);
    if (stringValue !== null) {
      return stringValue;
    }
  }
  return null;
}

export function joinStrings(values: unknown, separator = ", "): string | null {
  if (!Array.isArray(values)) {
    return asString(values);
  }

  const strings = values.map(asString).filter((value): value is string => value !== null);
  return strings.length > 0 ? strings.join(separator) : null;
}

export function compactObjectStrings(values: unknown): string | null {
  if (!values || typeof values !== "object") {
    return asString(values);
  }

  const strings = Object.values(values as Record<string, unknown>)
    .map(asString)
    .filter((value): value is string => value !== null);

  return strings.length > 0 ? strings.join(", ") : null;
}
