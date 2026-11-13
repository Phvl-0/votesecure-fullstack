FROM node:22-alpine AS build
WORKDIR /app
ENV NPM_CONFIG_FETCH_RETRIES=6 NPM_CONFIG_FETCH_TIMEOUT=600000 NPM_CONFIG_FETCH_RETRY_MINTIMEOUT=20000 NPM_CONFIG_FETCH_RETRY_MAXTIMEOUT=120000
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM nginxinc/nginx-unprivileged:alpine
USER root
RUN apk upgrade --no-cache
USER 101
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080

# DRILL: deliberately broken release, reverted right after
CMD ["sh", "-c", "echo drill-broken-release >&2; exit 1"]
