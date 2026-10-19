import json
from http.client import HTTPConnection
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPHandler, HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .models import UserError


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class LocalConnection(HTTPConnection):
    def connect(self):
        # On Windows, localhost often tries ::1 first and waits two seconds
        # before reaching ActivityWatch's IPv4 listener. Keep IPv6-only setups
        # working, without paying that failed connection cost on every request.
        if self.host != "localhost":
            return super().connect()
        original = self.host
        try:
            self.host = "127.0.0.1"
            try:
                super().connect()
            except OSError:
                self.host = "::1"
                super().connect()
        finally:
            self.host = original


class LocalHTTPHandler(HTTPHandler):
    def http_open(self, request):
        return self.do_open(LocalConnection, request)


class JsonHTTP:
    def __init__(self, base, headers=None, label="Service", local=False):
        self.base = base.rstrip("/")
        self.headers = headers or {}
        self.label = label
        self.opener = build_opener(NoRedirect(), *([ProxyHandler({}), LocalHTTPHandler()] if local else []))

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
                fix = ("Your key was not accepted. Create a new key in Clockify settings and run setup again, or check your workspace permissions."
                       if code in (401, 403) else "Check the service settings and try again.")
                raise UserError(f"{self.label} returned HTTP {code}. {fix}") from None
            except (URLError, TimeoutError, OSError):
                if self.label == "ActivityWatch":
                    raise UserError("Cannot reach ActivityWatch. Open ActivityWatch and try again.") from None
                raise UserError(f"Cannot reach {self.label}. Check your internet connection and try again. If a write was interrupted, review the day again before retrying.") from None
            except (ValueError, UnicodeError):
                raise UserError(f"{self.label} returned an unreadable response. Check its URL and version.") from None
