// Cognito sign-in: OIDC authorisation code flow with PKCE, ID token kept in an httpOnly cookie
const crypto = require('crypto');
const oidc = require('openid-client');
const { CognitoJwtVerifier } = require('aws-jwt-verify');
const { JwtBaseError, FetchError } = require('aws-jwt-verify/error');
const { GetParameterCommand } = require('@aws-sdk/client-ssm');

const TOKEN_COOKIE = 'govdata_auth_token';
const FLOW_COOKIE = 'govdata_auth_flow';
const FLOW_MAX_AGE_MS = 10 * 60 * 1000;

function createAuth({ ssm, configParam, baseUrl, cookieSecret }) {
  if (!configParam || !baseUrl || !cookieSecret) {
    throw new Error('COGNITO_CONFIG_PARAM, APP_BASE_URL and COOKIE_SECRET must all be set');
  }
  const cookieOpts = { httpOnly: true, secure: true, sameSite: 'lax', path: '/' };
  let configReady = null;
  let clientReady = null;

  // Each loads once and retries on the next request if it failed
  function loadConfig() {
    if (!configReady) {
      configReady = (async () => {
        const resp = await ssm.send(new GetParameterCommand({ Name: configParam, WithDecryption: true }));
        const cfg = JSON.parse(resp.Parameter.Value);
        const verifier = CognitoJwtVerifier.create({ userPoolId: cfg.user_pool_id, tokenUse: 'id', clientId: cfg.client_id });
        return { cfg, verifier };
      })().catch((err) => { configReady = null; throw err; });
    }
    return configReady;
  }

  function loadClient() {
    if (!clientReady) {
      clientReady = (async () => {
        const { cfg } = await loadConfig();
        const issuer = new URL(`https://cognito-idp.${cfg.region}.amazonaws.com/${cfg.user_pool_id}`);
        return oidc.discovery(issuer, cfg.client_id, undefined, oidc.ClientSecretBasic(cfg.client_secret));
      })().catch((err) => { clientReady = null; throw err; });
    }
    return clientReady;
  }

  function sign(value) {
    return value + '.' + crypto.createHmac('sha256', cookieSecret).update(value).digest('base64url');
  }

  function unsign(signed) {
    if (!signed) return null;
    const idx = signed.lastIndexOf('.');
    if (idx < 1) return null;
    const value = signed.substring(0, idx);
    const given = Buffer.from(signed.substring(idx + 1));
    const expected = Buffer.from(crypto.createHmac('sha256', cookieSecret).update(value).digest('base64url'));
    return given.length === expected.length && crypto.timingSafeEqual(given, expected) ? value : null;
  }

  // Only same-site relative paths, so the post-login redirect can't be pointed at another site
  function safeReturnTo(value) {
    return typeof value === 'string' && value.startsWith('/') && !value.startsWith('//') && !value.startsWith('/\\') ? value : '/';
  }

  async function login(req, res, next) {
    try {
      const client = await loadClient();
      const verifier = oidc.randomPKCECodeVerifier();
      const state = oidc.randomState();
      const flow = Buffer.from(JSON.stringify({ verifier, state, returnTo: safeReturnTo(req.query.returnTo) })).toString('base64url');
      res.cookie(FLOW_COOKIE, sign(flow), { ...cookieOpts, maxAge: FLOW_MAX_AGE_MS });
      const url = oidc.buildAuthorizationUrl(client, {
        redirect_uri: `${baseUrl}/auth/callback`,
        scope: 'openid email',
        code_challenge: await oidc.calculatePKCECodeChallenge(verifier),
        code_challenge_method: 'S256',
        state,
      });
      res.redirect(url.href);
    } catch (err) {
      next(err);
    }
  }

  async function callback(req, res) {
    const raw = unsign(req.cookies[FLOW_COOKIE]);
    res.clearCookie(FLOW_COOKIE, cookieOpts);
    if (!raw) return res.redirect('/auth/login');
    try {
      const flow = JSON.parse(Buffer.from(raw, 'base64url').toString());
      const client = await loadClient();
      const tokens = await oidc.authorizationCodeGrant(client, new URL(req.originalUrl, baseUrl), {
        pkceCodeVerifier: flow.verifier,
        expectedState: flow.state,
      });
      const maxAge = tokens.claims().exp * 1000 - Date.now();
      res.cookie(TOKEN_COOKIE, tokens.id_token, { ...cookieOpts, maxAge });
      res.redirect(safeReturnTo(flow.returnTo));
    } catch (err) {
      console.error('Sign-in callback failed:', err.message);
      res.status(401).send('Sign-in failed. <a href="/auth/login">Try again</a>.');
    }
  }

  async function signOut(req, res, next) {
    res.clearCookie(TOKEN_COOKIE, cookieOpts);
    try {
      const { cfg } = await loadConfig();
      const url = new URL(`https://${cfg.domain}/logout`);
      url.searchParams.set('client_id', cfg.client_id);
      url.searchParams.set('logout_uri', baseUrl);
      res.redirect(url.href);
    } catch (err) {
      next(err);
    }
  }

  // Every route registered after this needs a valid Cognito ID token
  async function requireUser(req, res, next) {
    const token = req.cookies[TOKEN_COOKIE];
    if (token) {
      try {
        const { verifier } = await loadConfig();
        const claims = await verifier.verify(token);
        req.user = { email: claims.email };
        res.locals.userEmail = claims.email;
        return next();
      } catch (err) {
        // Can't reach SSM or the JWKS endpoint: fail with 500 rather than loop through sign-in
        if (!(err instanceof JwtBaseError) || err instanceof FetchError) return next(err);
        res.clearCookie(TOKEN_COOKIE, cookieOpts);
      }
    }
    if (req.method === 'GET' && req.accepts('html')) {
      return res.redirect('/auth/login?returnTo=' + encodeURIComponent(req.originalUrl));
    }
    res.status(401).json({ error: 'Not signed in' });
  }

  function routes(app) {
    app.get('/auth/login', login);
    app.get('/auth/callback', callback);
    app.get('/sign-out', signOut);
  }

  return { routes, requireUser };
}

module.exports = { createAuth };
