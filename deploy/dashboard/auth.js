// Sign-in check for the dashboard: accepts the webapp's Cognito ID-token cookie, sends everyone else to the webapp's login
const { CognitoJwtVerifier } = require('aws-jwt-verify');
const { SSMClient, GetParameterCommand } = require('@aws-sdk/client-ssm');

const TOKEN_COOKIE = 'govdata_auth_token';

function createAuth({ region, configParam, baseUrl }) {
  if (!configParam || !baseUrl) {
    throw new Error('COGNITO_CONFIG_PARAM and APP_BASE_URL must both be set');
  }
  const ssm = new SSMClient({ region });
  let verifierReady = null;

  // Loads once and retries on the next request if it failed
  function loadVerifier() {
    if (!verifierReady) {
      verifierReady = (async () => {
        const resp = await ssm.send(new GetParameterCommand({ Name: configParam, WithDecryption: true }));
        const cfg = JSON.parse(resp.Parameter.Value);
        return CognitoJwtVerifier.create({ userPoolId: cfg.user_pool_id, tokenUse: 'id', clientId: cfg.client_id });
      })().catch((err) => { verifierReady = null; throw err; });
    }
    return verifierReady;
  }

  function tokenFromCookies(header) {
    const match = /(?:^|;\s*)govdata_auth_token=([^;]*)/.exec(header || '');
    return match ? match[1] : '';
  }

  async function requireUser(req, res, next) {
    const token = tokenFromCookies(req.headers.cookie);
    if (!token) return res.redirect(`${baseUrl}/auth/login?returnTo=${encodeURIComponent(req.originalUrl)}`);
    try {
      const verifier = await loadVerifier();
      const claims = await verifier.verify(token);
      req.user = { email: claims.email };
      next();
    } catch (err) {
      if (verifierReady === null) return next(err);
      res.redirect(`${baseUrl}/auth/login?returnTo=${encodeURIComponent(req.originalUrl)}`);
    }
  }

  return { requireUser, TOKEN_COOKIE };
}

module.exports = { createAuth };
