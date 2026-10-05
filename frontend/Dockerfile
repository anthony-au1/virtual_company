FROM node:24-alpine AS base

ENV PNPM_HOME="/pnpm"
ENV PATH="$PNPM_HOME:$PATH"

RUN corepack enable && corepack prepare pnpm@10.34.6 --activate

FROM base AS dependencies

WORKDIR /app

COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

FROM base AS build

WORKDIR /app

COPY --from=dependencies /app/node_modules ./node_modules
COPY . .
RUN pnpm build

FROM node:24-alpine AS runtime

ENV NODE_ENV="production"
ENV HOSTNAME="0.0.0.0"
ENV PORT="3000"

WORKDIR /app

RUN addgroup --system --gid 1001 nodejs \
    && adduser --system --uid 1001 nextjs

COPY --from=build --chown=nextjs:nodejs /app/.next/standalone ./

USER nextjs

EXPOSE 3000

CMD ["node", "server.js"]
