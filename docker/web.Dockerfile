# The web app. Build context is `./web`.
#
# Two stages so the runtime image carries no toolchain and no dev dependencies.
# `next build` runs in the builder, and `scripts/build-sw.mjs` runs immediately
# after it in the same stage, because the service worker's precache manifest is
# taken from the build output and cannot be produced without it.

FROM node:20-bookworm-slim AS build
WORKDIR /app

# Dependencies first, so a source-only change does not reinstall the tree.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
# `npm run build` is `next build && node scripts/build-sw.mjs`.
RUN npm run build


FROM node:20-bookworm-slim AS runtime
WORKDIR /app
ENV NODE_ENV=production \
    PORT=3000 \
    HOSTNAME=0.0.0.0

RUN useradd --system --uid 10001 --create-home akshar

COPY --from=build /app/package.json /app/package-lock.json ./
RUN npm ci --omit=dev && npm cache clean --force

COPY --from=build /app/.next ./.next
COPY --from=build /app/public ./public
COPY --from=build /app/next.config.ts ./next.config.ts

USER akshar
EXPOSE 3000

# `next start` serves the headers declared in `next.config.ts`, including
# COOP/COEP. Anything terminating TLS in front of this must pass them through
# unchanged — see `docs/deployment.md`.
CMD ["npx", "next", "start"]
