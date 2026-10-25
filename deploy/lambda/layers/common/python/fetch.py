"""HTTP GET for the ingest Lambdas: one User-Agent, a timeout on every call, retries on 5xx, 429 and connection errors."""
import json
import logging
import time
import urllib.error
import urllib.request

logger = logging.getLogger()

USER_AGENT = "govdata-data-platform/1.0"
RETRIES = 3


def request(url, timeout=60, headers=None, data=None, method=None, retries=RETRIES):
    """Open url and return the response; the caller reads it inside a with block. Raises after the last retry."""
    req = urllib.request.Request(url, data=data, method=method, headers={"User-Agent": USER_AGENT, **(headers or {})})
    for attempt in range(retries):
        try:
            return urllib.request.urlopen(req, timeout=timeout)  # nosec B310 nosemgrep: dynamic-urllib-use-detected, URLs are fixed per source
        except urllib.error.HTTPError as e:
            if attempt == retries - 1 or (e.code < 500 and e.code != 429):
                raise
            logger.warning(json.dumps({"message": "Retrying request", "url": url, "status": e.code, "attempt": attempt + 1}))
        except urllib.error.URLError as e:
            if attempt == retries - 1:
                raise
            logger.warning(json.dumps({"message": "Retrying request", "url": url, "error": str(e.reason), "attempt": attempt + 1}))
        time.sleep(5 * 2 ** attempt)  # nosemgrep: arbitrary-sleep, backoff between retries


def get(url, timeout=60, headers=None):
    """The response body as bytes."""
    with request(url, timeout, headers) as resp:
        return resp.read()


def get_json(url, timeout=60, headers=None):
    with request(url, timeout, {"Accept": "application/json", **(headers or {})}) as resp:
        return json.loads(resp.read())


def download(url, out, timeout=300, headers=None):
    """Stream the body to the file object out in 1 MB chunks and return the byte count."""
    size = 0
    with request(url, timeout, headers) as resp:
        while chunk := resp.read(1024 * 1024):
            out.write(chunk)
            size += len(chunk)
    return size
