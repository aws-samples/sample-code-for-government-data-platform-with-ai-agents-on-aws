#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["bedrock-agentcore==1.24.2", "playwright==1.64.0", "boto3==1.43.117"]
# ///
"""
Browser smoke test + audit for the Government Data Platform webapp, a liveness check rather than a data check.

Runs via AgentCore Browser Tool (managed cloud Chrome, no local browser needed). A fresh account with no ETL run still passes.
- Default: page rendering checks + agent query SSE timing → JUnit XML
- --audit: adds page load timing and broken link checks → JSON report

Usage (CI):
    AWS_REGION=<region> PREFIX_CODE=<prefix> uv run tests/browser_smoke_test.py --audit
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import hmac
import json
import os
import secrets
import sys
import time
from urllib.parse import urlparse

# ElementTree only writes the JUnit report; nothing untrusted is parsed
from xml.etree.ElementTree import Element, SubElement, ElementTree  # nosec B405

import boto3
from playwright.async_api import async_playwright, Page, TimeoutError as PlaywrightTimeout

REGION = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION", "")
PREFIX = os.environ.get("PREFIX_CODE", "")
COGNITO_TEST_EMAIL = "ci-test@example.com"
QUERY_TIMEOUT_MS = 180_000  # 3 min max per agent query
GEO_TEST_POLYGON = [[-2.26, 51.85], [-2.22, 51.85], [-2.22, 51.88], [-2.26, 51.88], [-2.26, 51.85]]

AUDIT_PAGES = [
    ("/", "Home"),
    ("/satellite", "Satellite analysis"),
    ("/admin", "Admin sessions"),
    ("/attribution", "Attribution"),
    ("/walkthrough/chat?scenario=1", "Scenario 1"),
    ("/walkthrough/chat?scenario=2", "Scenario 2"),
]


def _check_env():
    missing = [v for v, value in (("PREFIX_CODE", PREFIX), ("AWS_REGION", REGION)) if not value]
    if missing:
        print(f"❌ Missing required env vars: {', '.join(missing)}")
        sys.exit(1)


def resolve_webapp_url() -> str:
    cf = boto3.Session(region_name=REGION).client("cloudfront")
    for page in cf.get_paginator("list_distributions").paginate():
        for dist in page.get("DistributionList", {}).get("Items", []):
            if dist.get("Comment", "").startswith(f"{PREFIX}-webapp"):
                return f"https://{dist['DomainName']}"
    raise RuntimeError(f"No CloudFront distribution with comment starting '{PREFIX}-webapp'")


async def login(page: Page, base_url: str) -> None:
    """Authenticate via Cognito API and set the session cookie directly."""
    session = boto3.Session(region_name=REGION)
    ssm = session.client("ssm")
    resp = ssm.get_parameter(Name=f"/{PREFIX}/cognito/config", WithDecryption=True)
    cfg = json.loads(resp["Parameter"]["Value"])

    cognito = session.client("cognito-idp")
    # Fresh random password each run; no test credential is stored anywhere
    password = "Aa1!" + secrets.token_urlsafe(24)
    cognito.admin_set_user_password(
        UserPoolId=cfg["user_pool_id"], Username=COGNITO_TEST_EMAIL, Password=password, Permanent=True,
    )
    msg = COGNITO_TEST_EMAIL + cfg["client_id"]
    secret_hash = base64.b64encode(
        hmac.new(cfg["client_secret"].encode(), msg.encode(), hashlib.sha256).digest()
    ).decode()

    auth_resp = cognito.initiate_auth(
        ClientId=cfg["client_id"],
        AuthFlow="USER_PASSWORD_AUTH",
        AuthParameters={
            "USERNAME": COGNITO_TEST_EMAIL,
            "PASSWORD": password,
            "SECRET_HASH": secret_hash,
        },
    )
    id_token = auth_resp["AuthenticationResult"]["IdToken"]

    await page.goto(base_url, wait_until="domcontentloaded", timeout=30000)
    domain = urlparse(base_url).hostname
    await page.context.add_cookies([{
        "name": "govdata_auth_token",
        "value": id_token,
        "domain": domain,
        "path": "/",
        "httpOnly": True,
        "secure": True,
        "sameSite": "Lax",
    }])
    # Fails if the webapp no longer accepts the cookie set above
    resp = await page.goto(f"{base_url}/admin", wait_until="domcontentloaded", timeout=30000)
    if not resp or resp.status != 200 or urlparse(resp.url).path != "/admin":
        raise RuntimeError(f"Sign-in cookie not accepted: /admin ended at {resp.url if resp else 'no response'}")


async def check_page(page: Page, url: str, name: str, checks: list[str] | None = None) -> dict:
    """Navigate to a page and verify it loads. Returns result dict."""
    start = time.time()
    result = {"name": name, "url": url, "passed": False, "errors": [], "duration_ms": 0}
    console_errors = []
    own_host = urlparse(url).hostname

    # Console errors from the webapp's own origin only
    def _on_console(msg):
        source = (msg.location or {}).get("url", "")
        if msg.type == "error" and (not source or urlparse(source).hostname == own_host):
            console_errors.append(msg.text)

    page.on("console", _on_console)
    try:
        resp = await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        if resp and resp.status >= 400:
            result["errors"].append(f"HTTP {resp.status}")
            return result
        for text in checks or []:
            try:
                selector = text if text.startswith((".", "#", "[")) else f"text={text}"
                await page.wait_for_selector(selector, timeout=10000)
            except PlaywrightTimeout:
                result["errors"].append(f"Missing: '{text}'")
        real_errors = [e for e in console_errors if "favicon" not in e.lower()]
        if real_errors:
            result["errors"].append(f"Console errors: {real_errors[:3]}")
        result["passed"] = len(result["errors"]) == 0
    except Exception as e:
        result["errors"].append(str(e))
    finally:
        page.remove_listener("console", _on_console)
        result["duration_ms"] = int((time.time() - start) * 1000)
    return result


async def query_stream(page: Page, base_url: str, prompt: str, name: str, extra: dict | None = None) -> dict:
    """POST a prompt to /query-stream and time the full SSE response."""
    result = {"name": name, "prompt": prompt, "passed": False, "errors": [], "duration_ms": 0, "first_token_ms": 0}
    start = time.time()
    try:
        timing = await page.evaluate("""async ([url, prompt, extra, timeoutMs]) => {
            const start = performance.now();
            let firstToken = null;
            const controller = new AbortController();
            const timer = setTimeout(() => controller.abort(), timeoutMs);
            try {
                const resp = await fetch(url + '/query-stream', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        prompt,
                        messages: [{role: 'user', content: prompt}],
                        ...extra,
                    }),
                    signal: controller.signal,
                });
                if (!resp.ok) return {error: `HTTP ${resp.status}`, total: 0, firstToken: 0};
                const reader = resp.body.getReader();
                const decoder = new TextDecoder();
                let buffer = '';
                let textChunks = 0;
                let runError = null;
                while (true) {
                    const {done, value} = await reader.read();
                    if (done) break;
                    buffer += decoder.decode(value, {stream: true});
                    const lines = buffer.split('\\n');
                    buffer = lines.pop();
                    for (const line of lines) {
                        if (!line.startsWith('data: ')) continue;
                        let event;
                        try { event = JSON.parse(line.slice(6)); } catch (e) { continue; }
                        if (event.type === 'RUN_ERROR') runError = event.message || 'RUN_ERROR';
                        if (event.type === 'TEXT_MESSAGE_CONTENT' && event.delta) {
                            textChunks++;
                            if (firstToken === null) firstToken = performance.now() - start;
                        }
                    }
                }
                clearTimeout(timer);
                return {total: Math.round(performance.now() - start), firstToken: Math.round(firstToken || 0), textChunks, runError};
            } catch (e) {
                clearTimeout(timer);
                return {error: e.name === 'AbortError' ? 'Timeout' : e.message, total: Math.round(performance.now() - start), firstToken: 0};
            }
        }""", [base_url, prompt, extra or {}, QUERY_TIMEOUT_MS])

        if timing.get("error"):
            result["errors"].append(timing["error"])
            result["duration_ms"] = timing.get("total", 0)
        else:
            result["duration_ms"] = timing["total"]
            result["first_token_ms"] = timing["firstToken"]
            result["text_chunks"] = timing.get("textChunks", 0)
            if timing.get("runError"):
                result["errors"].append(f"RUN_ERROR: {timing['runError']}")
            if not result["text_chunks"]:
                result["errors"].append("No answer text streamed")
            result["passed"] = not result["errors"]
    except Exception as e:
        result["errors"].append(str(e))
        result["duration_ms"] = int((time.time() - start) * 1000)
    return result


def _print_result(r: dict, show_timing: bool = False):
    status = "✅" if r["passed"] else "❌"
    timing = f" ({r['duration_ms']}ms total, {r.get('first_token_ms', 0)}ms first token)" if show_timing else f" ({r['duration_ms']}ms)"
    print(f"  {status} {r['name']}{timing}")
    for err in r.get("errors", []):
        print(f"     ⚠️  {err}")


def _write_junit(results: list[dict], path: str):
    suite = Element("testsuite", name="browser-smoke", tests=str(len(results)),
                    failures=str(sum(1 for r in results if not r["passed"])),
                    time=str(sum(r["duration_ms"] for r in results) / 1000))
    for r in results:
        tc = SubElement(suite, "testcase", name=r["name"],
                        classname="browser_smoke_test", time=str(r["duration_ms"] / 1000))
        if not r["passed"]:
            SubElement(tc, "failure", message="; ".join(r["errors"]))
    ElementTree(suite).write(path, xml_declaration=True, encoding="unicode")
    print(f"📄 JUnit report: {path}")


async def run_smoke(page: Page, base_url: str) -> list[dict]:
    """Page rendering checks + agent query SSE timing. Returns results list."""
    results = []

    print("📋 Page rendering checks...\n")
    page_checks = [
        (f"{base_url}/", "Home page", ["[class*='govuk-heading']"]),
        (f"{base_url}/satellite", "Satellite analysis", ["#sat-map"]),
        (f"{base_url}/admin", "Admin sessions", [".govuk-table"]),
        (f"{base_url}/attribution", "Attribution", ["Open Government Licence", "Contains OS data"]),
        (f"{base_url}/walkthrough/chat?scenario=1", "Walkthrough scenario 1", ["#prompt"]),
        (f"{base_url}/walkthrough/chat?scenario=2", "Walkthrough scenario 2", ["#prompt"]),
    ]
    for url, name, checks in page_checks:
        r = await check_page(page, url, name, checks)
        _print_result(r)
        results.append(r)

    print("\n🤖 Main agent queries...\n")
    await page.goto(f"{base_url}/", wait_until="domcontentloaded")
    for prompt in [
        "Summarise Stroud.",
        "Create a choropleth map of deprivation.",
        "Prove that there is a north south divide using data.",
    ]:
        r = await query_stream(page, base_url, prompt, f"Main: {prompt[:50]}")
        _print_result(r, show_timing=True)
        results.append(r)

    print("\n🛰️  Geospatial agent queries...\n")
    await page.goto(f"{base_url}/satellite", wait_until="domcontentloaded")
    # Session id the page was rendered with
    session_id = await page.evaluate("() => (document.documentElement.innerHTML.match(/var sessionId = '([^']+)'/) || [])[1] || null")
    geo = {"mode": "geospatial", "coordinates": GEO_TEST_POLYGON}
    if session_id:
        geo["session_id"] = session_id
    for prompt, name in [
        ("What's here?", "Geo: What's here?"),
        ("What about water and vegetation?", "Geo: Water and vegetation"),
    ]:
        r = await query_stream(page, base_url, prompt, name, geo)
        _print_result(r, show_timing=True)
        results.append(r)

    return results



async def run_audit(page: Page, base_url: str) -> dict:
    """Performance and broken links. Returns report dict."""
    print("\n⏱️  Performance...")
    perf = []
    for path, name in AUDIT_PAGES:
        start = time.time()
        await page.goto(f"{base_url}{path}", wait_until="load", timeout=30000)
        ms = int((time.time() - start) * 1000)
        # Transfer size of the page and its resources
        size_kb = await page.evaluate("""() => Math.round(performance.getEntriesByType('navigation').concat(
            performance.getEntriesByType('resource')).reduce((n, e) => n + (e.transferSize || 0), 0) / 1024)""")
        flag = " ⚠️" if ms > 5000 else ""
        print(f"  {name:<40} {ms:>5}ms  {size_kb:>5}KB{flag}")
        perf.append({"page": name, "load_ms": ms, "size_kb": size_kb})

    print("\n🔗 Broken links...")
    broken = []
    checked: set = set()
    for path, name in AUDIT_PAGES:
        await page.goto(f"{base_url}{path}", wait_until="domcontentloaded", timeout=30000)
        items = await page.evaluate("""() => {
            const out = [];
            document.querySelectorAll('a[href]').forEach(a => {
                const h = a.getAttribute('href');
                if (h && !h.startsWith('#') && !h.startsWith('javascript') && !h.startsWith('mailto'))
                    out.push({type:'link', url:h, text:a.textContent.trim().substring(0,50)});
            });
            document.querySelectorAll('img[src]').forEach(img =>
                out.push({type:'image', url:img.getAttribute('src'), text:img.alt||''}));
            return out;
        }""")
        for item in items:
            url = item["url"]
            if url.startswith("/"):
                url = f"{base_url}{url}"
            elif not url.startswith("http"):
                continue
            if base_url not in url or url in checked:
                continue
            checked.add(url)
            try:
                resp = await page.context.request.get(url)
                if resp.status >= 400:
                    broken.append({"page": name, "type": item["type"], "url": item["url"], "status": resp.status})
            except Exception as exc:
                # A connection failure is reported as a broken link, same as a 4xx/5xx
                broken.append({"page": name, "type": item["type"], "url": item["url"], "status": f"error: {type(exc).__name__}"})

    if broken:
        for b in broken:
            print(f"  ❌ [{b['status']}] {b['type']} on {b['page']}: {b['url']}")
    else:
        print("  ✅ No broken links")

    slow = [p for p in perf if p["load_ms"] > 5000]
    print(f"\n{'='*55}")
    print(f"Slow pages (>5s): {len(slow)}  |  Broken links: {len(broken)}")

    report = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "base_url": base_url,
        "performance": perf,
        "broken_links": broken,
    }
    with open("tests/audit-report.json", "w") as f:
        json.dump(report, f, indent=2)
    print("📄 Audit report: tests/audit-report.json")
    return report


async def run_all(base_url: str, audit: bool = False):
    """Single browser session: smoke tests first, then audit if requested."""
    from bedrock_agentcore.tools.browser_client import browser_session

    print(f"🌐 Starting AgentCore Browser session in {REGION}...")
    with browser_session(REGION) as client:
        ws_url, headers = client.generate_ws_headers()
        print("✅ Browser session created\n")

        async with async_playwright() as pw:
            browser = await pw.chromium.connect_over_cdp(ws_url, headers=headers)
            try:
                context = browser.contexts[0] if browser.contexts else await browser.new_context()
                page = context.pages[0] if context.pages else await context.new_page()

                print(f"🔐 Logging in to {base_url}...")
                await login(page, base_url)
                print("✅ Logged in\n")

                # Smoke tests (always)
                results = await run_smoke(page, base_url)

                # Audit extras (if requested)
                if audit:
                    await run_audit(page, base_url)
            finally:
                await browser.close()

    # Summary + JUnit (always written)
    passed = sum(1 for r in results if r["passed"])
    total = len(results)
    print(f"\n{'='*55}")
    print(f"Results: {passed}/{total} passed")
    if passed < total:
        print("\nFailed:")
        for r in results:
            if not r["passed"]:
                print(f"  ❌ {r['name']}: {', '.join(r['errors'])}")
    else:
        print("🎉 All checks passed!")

    _write_junit(results, "tests/browser-smoke-results.xml")
    return passed == total


def main():
    _check_env()
    parser = argparse.ArgumentParser(description="Browser smoke test via AgentCore Browser Tool")
    parser.add_argument("--url", help="Webapp URL (auto-detected if not set)")
    parser.add_argument("--audit", action="store_true", help="Also run page load timing and broken link checks")
    args = parser.parse_args()
    base_url = args.url or resolve_webapp_url()
    print(f"🎯 Target: {base_url}\n")
    success = asyncio.run(run_all(base_url, audit=args.audit))
    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
