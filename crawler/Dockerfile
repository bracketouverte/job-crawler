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
RUN apk add --no-cache python3 make g++
COPY package*.json ./
RUN npm ci --omit=dev
COPY --from=build /app/dist ./dist
RUN mkdir -p /app/output
ENTRYPOINT ["node", "dist/cli.js"]
CMD ["--sources", "/data/sources", "--providers", "all", "--concurrency", "50", "--out", "/app/output/jobs.jsonl", "--report", "/app/output/report.json"]
