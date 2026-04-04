# ─── Stage 1: Build ───────────────────────────────────────────────
FROM node:18-alpine AS builder

WORKDIR /app

# Copy workspace root files for dependency resolution
COPY package.json package-lock.json ./
COPY apps/shiki/package.json ./apps/shiki/
COPY packages/web/package.json ./packages/web/
COPY packages/react-native/package.json ./packages/react-native/

# Install dependencies (including devDependencies for build)
RUN npm ci --workspace=apps/shiki

# Copy source
COPY apps/shiki/ ./apps/shiki/

# Build production bundle
WORKDIR /app/apps/shiki
RUN npm run build

# ─── Stage 2: Serve ───────────────────────────────────────────────
FROM nginx:1.27-alpine AS runtime

# Security: run as non-root
RUN addgroup -g 1001 -S shiki && \
    adduser -u 1001 -S shiki -G shiki

# Copy built assets
COPY --from=builder /app/apps/shiki/dist /usr/share/nginx/html

# Nginx config for SPA routing and security headers
COPY apps/shiki/nginx.conf /etc/nginx/conf.d/default.conf

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD wget --no-verbose --tries=1 --spider http://localhost:8080/health || exit 1

# Non-root user
RUN chown -R shiki:shiki /usr/share/nginx/html /var/cache/nginx /var/log/nginx /etc/nginx/conf.d && \
    touch /var/run/nginx.pid && chown shiki:shiki /var/run/nginx.pid

USER shiki

EXPOSE 8080

CMD ["nginx", "-g", "daemon off;"]
