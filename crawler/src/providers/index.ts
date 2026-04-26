import { ashbyCrawler } from "./ashby.js";
import { bamboohrCrawler } from "./bamboohr.js";
import { greenhouseCrawler } from "./greenhouse.js";
import { leverCrawler } from "./lever.js";
import { teamtailorCrawler } from "./teamtailor.js";
import { workableCrawler } from "./workable.js";
import { workdayCrawler } from "./workday.js";
import { Provider, ProviderCrawler } from "../types.js";

const crawlers = [
  ashbyCrawler,
  bamboohrCrawler,
  greenhouseCrawler,
  leverCrawler,
  teamtailorCrawler,
  workableCrawler,
  workdayCrawler,
] satisfies ProviderCrawler[];

export const crawlerByProvider = new Map<Provider, ProviderCrawler>(
  crawlers.map((crawler) => [crawler.provider, crawler])
);
