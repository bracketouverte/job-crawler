import { XMLParser } from "fast-xml-parser";
import { firstString, joinStrings } from "../normalizers.js";
import { CrawlContext, IdentifierSource, NormalizedJob, ProviderCrawler, SourceEntry } from "../types.js";

type RssDocument = {
  rss?: {
    channel?: {
      item?: RssItem | RssItem[];
    };
  };
};

type RssItem = {
  title?: unknown;
  link?: unknown;
  guid?: unknown;
  pubDate?: unknown;
  category?: unknown;
  description?: unknown;
  "teamtailor:department"?: unknown;
  "teamtailor:location"?: unknown;
};

const parser = new XMLParser({
  ignoreAttributes: false,
  removeNSPrefix: false,
  processEntities: false,
  parseTagValue: false,
  trimValues: true
});

export const teamtailorCrawler: ProviderCrawler = {
  provider: "teamtailor",
  async crawl(source: SourceEntry, context: CrawlContext): Promise<NormalizedJob[]> {
    const { identifier } = source as IdentifierSource;
    const xml = await context.http.getText(`https://${identifier}.teamtailor.com/jobs.rss`);
    const document = parser.parse(xml) as RssDocument;
    const items = normalizeArray(document.rss?.channel?.item);
    return items.map((item) => normalizeTeamtailorJob(identifier, item, context.fetchedAt()));
  }
};

export function normalizeTeamtailorJob(sourceKey: string, item: RssItem, fetchedAt: string): NormalizedJob {
  const link = firstString(item.link);
  const id = firstString(item.guid, link, item.title) ?? "unknown";
  return {
    provider: "teamtailor",
    source_key: sourceKey,
    job_id: id,
    title: firstString(item.title),
    location: firstString(item["teamtailor:location"]),
    employment_type: null,
    compensation: null,
    department: firstString(item["teamtailor:department"], joinStrings(item.category)),
    office: null,
    language: null,
    updated_at: parseDate(firstString(item.pubDate)),
    job_url: link,
    fetched_at: fetchedAt
  };
}

function normalizeArray<T>(value: T | T[] | undefined): T[] {
  if (value === undefined) {
    return [];
  }
  return Array.isArray(value) ? value : [value];
}

function parseDate(value: string | null): string | null {
  if (value === null) {
    return null;
  }
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toISOString();
}
