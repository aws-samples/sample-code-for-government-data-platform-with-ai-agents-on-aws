FROM public.ecr.aws/docker/library/node:26-slim
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

COPY govuk.scss ./
RUN npm run build:css && npm prune --omit=dev

RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser
COPY --chown=appuser:appgroup . .
USER appuser

EXPOSE 3001

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=2 \
  CMD ["node", "-e", "require('http').get('http://localhost:3001/health', r => process.exit(r.statusCode === 200 ? 0 : 1))"]

CMD ["node", "server.js"]

