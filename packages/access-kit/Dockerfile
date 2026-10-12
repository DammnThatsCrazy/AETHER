FROM node:22-bookworm-slim@sha256:c3de60bf2f9dd0ac6370e6117950ff62d6e339527e7472301c9c78a017978392 AS build

WORKDIR /workspace
RUN corepack enable
COPY . .
RUN pnpm install --filter @aether/access-kit --prod --frozen-lockfile

FROM node:22-bookworm-slim@sha256:c3de60bf2f9dd0ac6370e6117950ff62d6e339527e7472301c9c78a017978392

ENV NODE_ENV=production PORT=8080
WORKDIR /workspace
COPY --from=build /workspace/node_modules ./node_modules
COPY --from=build /workspace/packages/access-kit ./packages/access-kit
WORKDIR /workspace/packages/access-kit
USER node
EXPOSE 8080
CMD ["node", "./bin/aether-mcp-http.js"]
