# =============================================================================
# AETHER INGESTION SERVER — Multi-stage Dockerfile
# =============================================================================

# ---------------------------------------------------------------------------
# Stage 1: Base — Install dependencies
# ---------------------------------------------------------------------------
FROM node:20-slim AS base

WORKDIR /app

# Copy root workspace files
COPY package.json tsconfig.json ./

# Copy package-level package.json files for workspace resolution
COPY packages/common/package.json packages/common/package.json
COPY packages/logger/package.json packages/logger/package.json
COPY packages/auth/package.json packages/auth/package.json
COPY packages/cache/package.json packages/cache/package.json
COPY packages/events/package.json packages/events/package.json
COPY services/ingestion/package.json services/ingestion/package.json

# Install dependencies
RUN npm install --workspace=packages/common \
    --workspace=packages/logger \
    --workspace=packages/auth \
    --workspace=packages/cache \
    --workspace=packages/events \
    --workspace=services/ingestion

# Copy all source files
COPY packages/ packages/
COPY services/ services/

# ---------------------------------------------------------------------------
# Stage 2: Development — tsx watch for hot-reload
# ---------------------------------------------------------------------------
FROM base AS dev

RUN npm install -g tsx

EXPOSE 3001

CMD ["tsx", "watch", "services/ingestion/src/index.ts"]

# ---------------------------------------------------------------------------
# Stage 3: Build — Compile TypeScript
# ---------------------------------------------------------------------------
FROM base AS build

# Copy tsconfig files for all workspaces
COPY packages/common/tsconfig.json packages/common/tsconfig.json
COPY packages/logger/tsconfig.json packages/logger/tsconfig.json
COPY packages/auth/tsconfig.json packages/auth/tsconfig.json
COPY packages/cache/tsconfig.json packages/cache/tsconfig.json
COPY packages/events/tsconfig.json packages/events/tsconfig.json
COPY services/ingestion/tsconfig.json services/ingestion/tsconfig.json

RUN npx tsc -b tsconfig.build.json

# ---------------------------------------------------------------------------
# Stage 4: Production — Minimal runtime image
# ---------------------------------------------------------------------------
FROM node:20-slim AS production

WORKDIR /app

# Copy built artifacts
COPY --from=build /app/package.json ./
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/packages/common/dist ./packages/common/dist
COPY --from=build /app/packages/common/package.json ./packages/common/package.json
COPY --from=build /app/packages/logger/dist ./packages/logger/dist
COPY --from=build /app/packages/logger/package.json ./packages/logger/package.json
COPY --from=build /app/packages/auth/dist ./packages/auth/dist
COPY --from=build /app/packages/auth/package.json ./packages/auth/package.json
COPY --from=build /app/packages/cache/dist ./packages/cache/dist
COPY --from=build /app/packages/cache/package.json ./packages/cache/package.json
COPY --from=build /app/packages/events/dist ./packages/events/dist
COPY --from=build /app/packages/events/package.json ./packages/events/package.json
COPY --from=build /app/services/ingestion/dist ./services/ingestion/dist
COPY --from=build /app/services/ingestion/package.json ./services/ingestion/package.json

ENV NODE_ENV=production
EXPOSE 3001

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD node -e "fetch('http://localhost:3001/health').then(r => process.exit(r.ok ? 0 : 1)).catch(() => process.exit(1))"

USER node

CMD ["node", "services/ingestion/dist/index.js"]
