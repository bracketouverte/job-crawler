FROM node:24-alpine AS deps
WORKDIR /app
RUN apk add --no-cache python3 make g++
COPY package*.json ./
RUN npm ci

FROM deps AS build
COPY tsconfig.json ./
COPY src ./src
RUN npm run build

FROM node:24-alpine
WORKDIR /app
ENV NODE_ENV=production
RUN apk add --no-cache python3 make g++ jq
COPY package*.json ./
RUN npm ci --omit=dev
COPY --from=build /app/dist ./dist
COPY post-crawl.sh /app/post-crawl.sh
RUN chmod +x /app/post-crawl.sh
RUN mkdir -p /app/output
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["--sources", "/data/sources", "--providers", "all", "--concurrency", "50", "--out", "/app/output/jobs.jsonl", "--report", "/app/output/report.json"]
