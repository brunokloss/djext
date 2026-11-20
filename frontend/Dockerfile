# The frontend's production image: Next's standalone server on :3000. Not
# needed on Vercel, which builds the app itself (see docs/deployment.md).
#
# Next reads these when it builds (the /api rewrite, the CSP, the browser's
# Sentry, the project's names), so they are build args, not runtime env:
#   docker build --build-arg BACKEND_URL=http://backend:8000 ...
# At runtime BACKEND_URL is read again by the server code (the proxy and
# serverApi()); give it the same value.

FROM node:24-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci
COPY . .
ARG BACKEND_URL=http://localhost:8000
ARG DJANGO_ADMIN_URL=""
ARG STORAGE_BUCKET_URL=""
ARG NEXT_PUBLIC_PROJECT_SLUG=djext
ARG NEXT_PUBLIC_PROJECT_NAME=""
ARG NEXT_PUBLIC_SENTRY_DSN=""
ARG NEXT_PUBLIC_SENTRY_ENVIRONMENT=""
ARG NEXT_PUBLIC_SENTRY_TRACES_SAMPLE_RATE=1
ENV NEXT_OUTPUT=standalone NEXT_TELEMETRY_DISABLED=1
RUN npm run build && mkdir -p public

FROM node:24-slim
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 HOSTNAME=0.0.0.0 PORT=3000
COPY --from=build --chown=node:node /app/.next/standalone ./
COPY --from=build --chown=node:node /app/.next/static ./.next/static
COPY --from=build --chown=node:node /app/public ./public
USER node
EXPOSE 3000
CMD ["node", "server.js"]
