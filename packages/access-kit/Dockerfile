FROM node:22-bookworm-slim AS build

WORKDIR /workspace
RUN corepack enable
COPY . .
RUN pnpm install --filter @aether/access-kit --prod --frozen-lockfile

FROM node:22-bookworm-slim

ENV NODE_ENV=production PORT=8080
WORKDIR /workspace
COPY --from=build /workspace/node_modules ./node_modules
COPY --from=build /workspace/packages/access-kit ./packages/access-kit
WORKDIR /workspace/packages/access-kit
USER node
EXPOSE 8080
CMD ["node", "./bin/aether-mcp-http.js"]
