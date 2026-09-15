"""Concurrent image-URL health checks.

Answers, per URL: does it resolve, is it actually an image, and how big is it.
Results are cached in-process so re-running a build never re-hits a URL.
"""

from __future__ import annotations

import io
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Callable, Iterable, Sequence
from urllib.parse import urlparse

import requests

try:  # Pillow is optional -- without it we simply skip dimension reporting.
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None  # type: ignore[assignment]

USER_AGENT = "mmf-image-links/1.0 (+image link validator)"
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".tif", ".tiff", ".bmp", ".avif")
_SNIFF_BYTES = 262_144  # enough for a JPEG/PNG header in practice


@dataclass(frozen=True)
class UrlCheck:
    url: str
    ok: bool
    status: int | None = None
    content_type: str | None = None
    bytes_len: int | None = None
    width: int | None = None
    height: int | None = None
    error: str | None = None

    @property
    def is_image(self) -> bool:
        if self.content_type:
            return self.content_type.split(";")[0].strip().lower().startswith("image/")
        return self.url.lower().split("?")[0].endswith(IMAGE_EXTENSIONS)

    @property
    def longest_side(self) -> int | None:
        if self.width and self.height:
            return max(self.width, self.height)
        return None

    def label(self) -> str:
        if self.ok and self.longest_side:
            return f"{self.width}x{self.height}"
        if self.ok:
            return "OK"
        if self.status:
            return f"HTTP {self.status}"
        return self.error or "unreachable"


def looks_like_url(value: str) -> bool:
    parsed = urlparse(value.strip())
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def _measure(payload: bytes) -> tuple[int | None, int | None]:
    if Image is None or not payload:
        return None, None
    try:
        with Image.open(io.BytesIO(payload)) as img:
            return img.width, img.height
    except Exception:
        return None, None


def check_url(
    url: str,
    *,
    session: requests.Session | None = None,
    timeout: float = 10.0,
    measure: bool = True,
) -> UrlCheck:
    url = url.strip()
    if not looks_like_url(url):
        return UrlCheck(url=url, ok=False, error="not an http(s) URL")

    sess = session or requests.Session()
    headers = {"User-Agent": USER_AGENT}
    try:
        if not measure:
            # Cheap path: HEAD, and only fall back to GET if the server is one of
            # the many that reject or lie about HEAD.
            response = sess.head(url, timeout=timeout, allow_redirects=True, headers=headers)
            if response.status_code < 400 and response.headers.get("Content-Type"):
                return UrlCheck(
                    url=url,
                    ok=True,
                    status=response.status_code,
                    content_type=response.headers.get("Content-Type"),
                    bytes_len=_declared_length(response.headers.get("Content-Length")),
                )

        # Measuring dimensions needs bytes, so go straight to a ranged GET --
        # a preceding HEAD would just double the request count for nothing.
        get_headers = dict(headers)
        if measure:
            get_headers["Range"] = f"bytes=0-{_SNIFF_BYTES - 1}"
        response = sess.get(url, timeout=timeout, allow_redirects=True,
                            headers=get_headers, stream=True)
        try:
            payload = b""
            if response.status_code < 400:
                for chunk in response.iter_content(8192):
                    payload += chunk
                    if len(payload) >= _SNIFF_BYTES:
                        break
        finally:
            response.close()  # release the pooled connection even mid-stream

        width, height = _measure(payload) if measure else (None, None)
        size = _full_length(response.headers)
        return UrlCheck(
            url=url,
            ok=response.status_code < 400,
            status=response.status_code,
            content_type=response.headers.get("Content-Type"),
            bytes_len=size,
            width=width,
            height=height,
            error=None if response.status_code < 400 else f"HTTP {response.status_code}",
        )
    except requests.Timeout:
        return UrlCheck(url=url, ok=False, error=f"timed out after {timeout:g}s")
    except requests.RequestException as exc:
        return UrlCheck(url=url, ok=False, error=type(exc).__name__)
    finally:
        if session is None:
            sess.close()


def _declared_length(value: str | None) -> int | None:
    return int(value) if value and value.isdigit() else None


def _full_length(headers) -> int | None:
    """Total size of the resource, not of the slice we happened to ask for.

    On a 206 the Content-Length describes the range, so it must not be used --
    and `Content-Range: bytes 0-99/*` means the server won't say.
    """
    content_range = headers.get("Content-Range")
    if content_range:
        match = re.search(r"/(\d+)\s*$", content_range)
        return int(match.group(1)) if match else None
    return _declared_length(headers.get("Content-Length"))


def check_urls(
    urls: Iterable[str],
    *,
    workers: int = 12,
    timeout: float = 10.0,
    measure: bool = True,
    progress: Callable[[int, int], None] | None = None,
) -> dict[str, UrlCheck]:
    """Check a batch of URLs in parallel. Duplicates are checked once."""
    unique: list[str] = list(dict.fromkeys(u.strip() for u in urls if u and u.strip()))
    results: dict[str, UrlCheck] = {}
    if not unique:
        return results

    total = len(unique)
    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(pool_connections=workers, pool_maxsize=workers)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    try:
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            futures = {
                pool.submit(check_url, url, session=session, timeout=timeout, measure=measure): url
                for url in unique
            }
            for done, future in enumerate(as_completed(futures), start=1):
                url = futures[future]
                try:
                    results[url] = future.result()
                except Exception as exc:  # pragma: no cover -- defensive
                    results[url] = UrlCheck(url=url, ok=False, error=type(exc).__name__)
                if progress:
                    progress(done, total)
    finally:
        session.close()
    return results


def broken_urls(checks: dict[str, UrlCheck]) -> list[str]:
    return [url for url, check in checks.items() if not check.ok]


def undersized(checks: dict[str, UrlCheck], min_longest_side: int) -> list[str]:
    """URLs whose longest side is under a marketplace minimum (Amazon wants 1600)."""
    out = []
    for url, check in checks.items():
        side = check.longest_side
        if check.ok and side is not None and side < min_longest_side:
            out.append(url)
    return out


def summarize(checks: dict[str, UrlCheck]) -> dict[str, int]:
    ok = sum(1 for c in checks.values() if c.ok)
    not_image = sum(1 for c in checks.values() if c.ok and not c.is_image)
    return {
        "checked": len(checks),
        "ok": ok,
        "broken": len(checks) - ok,
        "not_an_image": not_image,
    }


def as_rows(checks: dict[str, UrlCheck], order: Sequence[str] | None = None) -> list[dict[str, object]]:
    keys = list(order) if order else list(checks)
    rows = []
    for url in keys:
        check = checks.get(url)
        if check is None:
            continue
        rows.append({
            "Image Link": url,
            "Status": check.status,
            "Result": "OK" if check.ok else "BROKEN",
            "Content type": check.content_type,
            "Width": check.width,
            "Height": check.height,
            "Size (KB)": round(check.bytes_len / 1024, 1) if check.bytes_len else None,
            "Error": check.error,
        })
    return rows
