FROM public.ecr.aws/docker/library/node:26-slim

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY govuk.scss ./
RUN npm run build:css && npm prune --omit=dev

COPY . .

RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser && chown -R appuser /app
USER appuser

EXPOSE 3000

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=2 \
  CMD ["node", "-e", "require('http').get('http://localhost:3000/health', r => process.exit(r.statusCode === 200 ? 0 : 1))"]

CMD ["node", "--require", "@aws/aws-distro-opentelemetry-node-autoinstrumentation/register", "server.js"]

