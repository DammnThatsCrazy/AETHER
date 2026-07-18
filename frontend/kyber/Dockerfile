# =============================================================================
# Kyber operator console — production image.
#
# Build context is the REPOSITORY ROOT (npm workspaces monorepo). The app lives
# at frontend/kyber and depends on three workspace packages:
#   @aether/shared -> packages/shared
#   @aether/web    -> packages/web
#   @aether/ui     -> frontend/shared
#
# Referenced from the root docker-compose.yml `kyber` service as:
#   build: { context: ., dockerfile: frontend/kyber/Dockerfile }
# =============================================================================

# ─── Stage 1: Build ───────────────────────────────────────────────
FROM node:18-alpine AS builder

WORKDIR /app

# Copy workspace root manifests first (layer-cache friendly)
COPY package.json package-lock.json ./
COPY frontend/kyber/package.json    ./frontend/kyber/
COPY frontend/shared/package.json   ./frontend/shared/
COPY packages/shared/package.json   ./packages/shared/
COPY packages/web/package.json      ./packages/web/

# Install the kyber workspace subtree (pulls its workspace deps)
RUN npm ci --workspace=frontend/kyber

# Copy workspace package source (shared/ui/web are TypeScript-source packages)
COPY packages/shared/ ./packages/shared/
COPY packages/web/    ./packages/web/
COPY frontend/shared/ ./frontend/shared/

# Copy app source
COPY frontend/kyber/ ./frontend/kyber/

# Auth0 and API config — baked into the Vite bundle at build time
ARG VITE_AUTH0_DOMAIN
ARG VITE_AUTH0_CLIENT_ID
ARG VITE_AUTH0_AUDIENCE
ARG VITE_API_BASE_URL
ARG VITE_WS_BASE_URL

WORKDIR /app/frontend/kyber
RUN npm run build

# ─── Stage 2: Serve ───────────────────────────────────────────────
FROM nginx:1.27-alpine AS runtime

# Security: run as non-root
RUN addgroup -g 1001 -S kyber && \
    adduser  -u 1001 -S kyber -G kyber

# Copy built assets
COPY --from=builder /app/frontend/kyber/dist /usr/share/nginx/html

# Nginx config stored as a template; entrypoint substitutes ${BACKEND_URL}
COPY frontend/kyber/nginx.conf    /etc/nginx/templates/default.conf.template
COPY frontend/kyber/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD wget --no-verbose --tries=1 --spider http://localhost:8080/health || exit 1

RUN chown -R kyber:kyber /usr/share/nginx/html /var/cache/nginx /var/log/nginx /etc/nginx/conf.d && \
    mkdir -p /etc/nginx/conf.d && \
    touch /var/run/nginx.pid && chown kyber:kyber /var/run/nginx.pid

USER kyber

EXPOSE 8080

ENTRYPOINT ["/entrypoint.sh"]
