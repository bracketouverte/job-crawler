import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { Provider, providers, SourceEntry, SourceFile } from "./types.js";

const providerSet = new Set<string>(providers);

export function sourceKey(provider: Provider, source: SourceEntry): string {
  if ("identifier" in source) {
    return source.identifier;
  }
  return `${source.tenant}/${source.shard}/${source.site}`;
}

export function isProvider(value: string): value is Provider {
  return providerSet.has(value);
}

export function parseProviderList(value: string): Provider[] {
  if (value === "all") {
    return [...providers];
  }

  const selected = value.split(",").map((item) => item.trim()).filter(Boolean);
  if (selected.length === 0) {
    throw new Error("--providers must not be empty");
  }

  return selected.map((item) => {
    if (!isProvider(item)) {
      throw new Error(`Unsupported provider "${item}". Expected one of: ${providers.join(", ")}, all`);
    }
    return item;
  });
}

export async function loadSourceFile(sourcesDir: string, provider: Provider): Promise<SourceFile> {
  const file = join(sourcesDir, `${provider}.json`);
  const raw = await readFile(file, "utf8");
  const parsed = JSON.parse(raw) as Partial<SourceFile>;

  if (parsed.provider !== provider) {
    throw new Error(`${file} declares provider "${String(parsed.provider)}", expected "${provider}"`);
  }
  if (!Array.isArray(parsed.companies)) {
    throw new Error(`${file} must contain a companies array`);
  }

  for (const [index, source] of parsed.companies.entries()) {
    validateSource(provider, source, `${file} companies[${index}]`);
  }

  return parsed as SourceFile;
}

function validateSource(provider: Provider, source: unknown, label: string): asserts source is SourceEntry {
  if (!source || typeof source !== "object") {
    throw new Error(`${label} must be an object`);
  }

  const candidate = source as Record<string, unknown>;
  if (provider === "workday") {
    for (const key of ["tenant", "shard", "site"]) {
      if (typeof candidate[key] !== "string" || candidate[key] === "") {
        throw new Error(`${label}.${key} must be a non-empty string`);
      }
    }
    return;
  }

  if (typeof candidate.identifier !== "string" || candidate.identifier === "") {
    throw new Error(`${label}.identifier must be a non-empty string`);
  }
}
