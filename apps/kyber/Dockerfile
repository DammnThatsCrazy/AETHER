# ─── Stage 1: Build ───────────────────────────────────────────────
FROM node:18-alpine AS builder

WORKDIR /app

# Copy workspace root files for dependency resolution
COPY package.json package-lock.json ./
COPY apps/kyber/package.json ./apps/kyber/
COPY packages/shared/package.json ./packages/shared/
COPY packages/web/package.json ./packages/web/
COPY packages/react-native/package.json ./packages/react-native/

# Install dependencies (including devDependencies for build)
RUN npm ci --workspace=apps/kyber

# Copy source
COPY apps/kyber/ ./apps/kyber/

# Build production bundle
WORKDIR /app/apps/kyber
RUN npm run build

# ─── Stage 2: Serve ───────────────────────────────────────────────
FROM nginx:1.27-alpine AS runtime

# Security: run as non-root
RUN addgroup -g 1001 -S kyber && \
    adduser -u 1001 -S kyber -G kyber

# Copy built assets
COPY --from=builder /app/apps/kyber/dist /usr/share/nginx/html

# Nginx config for SPA routing and security headers
COPY apps/kyber/nginx.conf /etc/nginx/conf.d/default.conf

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD wget --no-verbose --tries=1 --spider http://localhost:8080/health || exit 1

# Non-root user
RUN chown -R kyber:kyber /usr/share/nginx/html /var/cache/nginx /var/log/nginx /etc/nginx/conf.d && \
    touch /var/run/nginx.pid && chown kyber:kyber /var/run/nginx.pid

USER kyber

EXPOSE 8080

CMD ["nginx", "-g", "daemon off;"]
