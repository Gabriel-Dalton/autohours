import json
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .models import UserError


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class JsonHTTP:
    def __init__(self, base, headers=None, label="Service", local=False):
        self.base = base.rstrip("/")
        self.headers = headers or {}
        self.label = label
        self.opener = build_opener(NoRedirect(), *([ProxyHandler({})] if local else []))

    def request(self, method, path, body=None):
        data = None if body is None else json.dumps(body).encode("utf-8")
        headers = {"Accept": "application/json", **self.headers}
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = Request(self.base + path, data=data, headers=headers, method=method)
        for attempt in range(4):
            try:
                with self.opener.open(request, timeout=30) as response:
                    return json.load(response)
            except HTTPError as exc:
                if exc.code == 429 and attempt < 3:
                    retry = exc.headers.get("Retry-After", "")
                    delay = min(float(retry), 5) if retry.isdigit() else 0.5 * 2**attempt
                    exc.close()
                    time.sleep(delay)
                    continue
                code = exc.code
                exc.close()
                fix = "Check CLOCKIFY_API_KEY and your workspace permissions." if code in (401, 403) else "Check the service settings and try again."
                raise UserError(f"{self.label} returned HTTP {code}. {fix}") from None
            except (URLError, TimeoutError, OSError):
                raise UserError(f"Cannot reach {self.label}. Check that it is running and your connection works. If a write failed, preview again before retrying.") from None
            except (ValueError, UnicodeError):
                raise UserError(f"{self.label} returned an unreadable response. Check its URL and version.") from None
