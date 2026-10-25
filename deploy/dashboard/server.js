const crypto = require('crypto');
const express = require('express');
const nunjucks = require('nunjucks');
const path = require('path');
const { defaultProvider } = require('@aws-sdk/credential-provider-node');
const { HttpRequest } = require('@smithy/protocol-http');
const { SignatureV4 } = require('@smithy/signature-v4');
const { createAuth } = require('./auth');

const app = express();
const PORT = process.env.PORT || 3001;
const DASHBOARD_API_URL = process.env.DASHBOARD_API_URL || '';
const DASHBOARD_API_REGION = process.env.DASHBOARD_API_REGION || process.env.AWS_REGION || 'eu-west-2';
const REFRESH_INTERVAL = parseInt(process.env.REFRESH_INTERVAL || '15000', 10);
const auth = createAuth({
  region: DASHBOARD_API_REGION,
  configParam: process.env.COGNITO_CONFIG_PARAM,
  baseUrl: process.env.APP_BASE_URL,
});

nunjucks.configure(path.join(__dirname, 'views'), {
  autoescape: true,
  express: app,
  noCache: process.env.NODE_ENV !== 'production',
});

// The ALB forwards /dashboard and /dashboard/* only
app.use('/dashboard/assets', express.static(path.join(__dirname, 'node_modules/govuk-frontend/dist/govuk/assets')));
app.get('/dashboard/govuk-built.css', (req, res) => res.sendFile(path.join(__dirname, 'govuk-built.css')));
app.get('/dashboard/chart.js', (req, res) => { res.type('application/javascript'); res.sendFile(path.join(__dirname, 'node_modules/chart.js/dist/chart.umd.js')); });

app.get('/health', (req, res) => res.json({ status: 'ok' }));

// Everything below shows other users' questions and charts; the stylesheet and health check above stay open
app.use(auth.requireUser);

app.get('/dashboard', (req, res) => {
  res.render('dashboard.html', { refreshInterval: REFRESH_INTERVAL });
});

app.get('/dashboard/api/metrics', metricsHandler);

async function metricsHandler(req, res) {
  if (!DASHBOARD_API_URL) {
    return res.json({
      platform: 'govdata',
      timestamp: new Date().toISOString(),
      metrics: { total_questions_asked: 0, sql_queries_executed: 0, areas_explored: 0, walkthroughs: 0 },
      coverage: { data_sources: 0, total_rows: 0 },
      live: {},
      latest_chart: null,
    });
  }
  try {
    const resp = await fetchSigned(DASHBOARD_API_URL);
    if (!resp.ok) throw new Error(`metrics API returned ${resp.status}`);
    res.json(await resp.json());
  } catch (err) {
    console.error('Metrics fetch error:', err.message);
    res.status(502).json({ error: 'Failed to fetch metrics' });
  }
}

// Node's crypto as the hash the signer wants, in place of a separate sha256 package
class Sha256 {
  constructor(secret) { this.hash = secret ? crypto.createHmac('sha256', secret) : crypto.createHash('sha256'); }
  update(data) { this.hash.update(data); }
  async digest() { return new Uint8Array(this.hash.digest()); }
}

const signer = new SignatureV4({ service: 'execute-api', region: DASHBOARD_API_REGION, credentials: defaultProvider(), sha256: Sha256 });

// The metrics route is IAM-protected; the task role signs the request
async function fetchSigned(url) {
  const target = new URL(url);
  const request = new HttpRequest({
    method: 'GET',
    protocol: target.protocol,
    hostname: target.hostname,
    path: target.pathname,
    headers: { host: target.hostname },
  });
  const signed = await signer.sign(request);
  return fetch(url, { method: 'GET', headers: signed.headers, signal: AbortSignal.timeout(10000) });
}

const server = app.listen(PORT, '0.0.0.0', () => console.log(`Dashboard on :${PORT}`));
process.on('SIGTERM', () => server.close(() => process.exit(0)));
