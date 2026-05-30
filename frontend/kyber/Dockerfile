# ─── Stage 1: Build ───────────────────────────────────────────────
FROM node:18-alpine AS builder

WORKDIR /app

# Copy workspace root manifests first (layer-cache friendly)
COPY package.json package-lock.json ./
COPY apps/kyber/package.json             ./apps/kyber/
COPY packages/shared/package.json        ./packages/shared/
COPY packages/web/package.json           ./packages/web/
COPY packages/react-native/package.json  ./packages/react-native/

# Install all workspace dependencies
RUN npm ci --workspace=apps/kyber

# Copy workspace package source (shared + web are TypeScript-source packages)
COPY packages/shared/ ./packages/shared/
COPY packages/web/    ./packages/web/

# Copy app source
COPY apps/kyber/ ./apps/kyber/

# Auth0 and API config — baked into the Vite bundle at build time
ARG VITE_AUTH0_DOMAIN
ARG VITE_AUTH0_CLIENT_ID
ARG VITE_AUTH0_AUDIENCE
ARG VITE_API_BASE_URL
ARG VITE_WS_BASE_URL

WORKDIR /app/apps/kyber
RUN npm run build

# ─── Stage 2: Serve ───────────────────────────────────────────────
FROM nginx:1.27-alpine AS runtime

# Security: run as non-root
RUN addgroup -g 1001 -S kyber && \
    adduser  -u 1001 -S kyber -G kyber

# Copy built assets
COPY --from=builder /app/apps/kyber/dist /usr/share/nginx/html

# Nginx config stored as a template; entrypoint substitutes ${BACKEND_URL}
COPY apps/kyber/nginx.conf    /etc/nginx/templates/default.conf.template
COPY apps/kyber/entrypoint.sh /entrypoint.sh
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
