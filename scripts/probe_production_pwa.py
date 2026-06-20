#!/usr/bin/env python3
"""Probe production homepage + service worker for PWA cache diagnostics."""
import json
import re
import urllib.request

BASE = "https://www.gadaadictionary.com"


def fetch(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": "gadaa-pwa-probe/1.0", "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return {
            "url": url,
            "status": resp.status,
            "headers": dict(resp.headers),
            "body": resp.read().decode("utf-8", "replace"),
        }


def main():
    home = fetch(f"{BASE}/")
    sw = fetch(f"{BASE}/service-worker.js")
    html = home["body"]
    sw_versioned = None
    build = (home["headers"].get("X-Gadaa-Build") or home["headers"].get("x-gadaa-build") or "").strip()
    if not build:
        build = _meta(html, "gadaa-build-token")
    if build:
        try:
            sw_versioned = fetch(f"{BASE}/service-worker.js?v={build}")
        except Exception as e:
            sw_versioned = {"error": repr(e)}

    report = {
        "homepage": {
            "status": home["status"],
            "bytes": len(html.encode("utf-8")),
            "x_gadaa_build": build,
            "cache_control": home["headers"].get("Cache-Control") or home["headers"].get("cache-control"),
            "has_learn_languages": "🌍 Learn Languages" in html,
            "has_english_class": "🎓 English Class" in html,
            "has_old_learn_label": bool(re.search(r'href="/learn"[^>]*>🎓 Learn<', html)),
            "has_gadaa_build_meta": 'name="gadaa-build-token"' in html,
            "has_sw_canonical_meta": 'name="gadaa-sw-canonical-url"' in html,
            "has_gadaa_sw_url_script": "__GADAA_SW_URL" in html,
            "pwa_ui_versioned": bool(re.search(r"pwa-ui\.js\?v=", html)),
            "build_meta_value": _meta(html, "gadaa-build-token"),
            "sw_canonical_meta": _meta(html, "gadaa-sw-canonical-url"),
        },
        "service_worker_unversioned": {
            "status": sw["status"],
            "x_gadaa_build": sw["headers"].get("X-Gadaa-Build") or sw["headers"].get("x-gadaa-build"),
            "x_sw_cache_version": sw["headers"].get("X-SW-Cache-Version") or sw["headers"].get("x-sw-cache-version"),
            "cache_version_in_body": _sw_cache_line(sw["body"]),
            "has_placeholder": "__GADAA_CACHE_VERSION__" in sw["body"],
            "has_navigation_network_first": "navigationNetworkFirst" in sw["body"],
            "has_nav_timeout": "NAV_TIMEOUT_MS" in sw["body"],
            "has_stale_while_revalidate": "staleWhileRevalidate" in sw["body"],
        },
    }
    if isinstance(sw_versioned, dict) and "body" in sw_versioned:
        report["service_worker_versioned"] = {
            "url": sw_versioned["url"],
            "status": sw_versioned["status"],
            "x_gadaa_build": sw_versioned["headers"].get("X-Gadaa-Build"),
            "x_sw_cache_version": sw_versioned["headers"].get("X-SW-Cache-Version"),
            "cache_version_in_body": _sw_cache_line(sw_versioned["body"]),
        }
    else:
        report["service_worker_versioned"] = sw_versioned

    print(json.dumps(report, indent=2))


def _meta(html, name):
    m = re.search(rf'<meta\s+name="{re.escape(name)}"\s+content="([^"]*)"', html, re.I)
    return m.group(1) if m else ""


def _sw_cache_line(body):
    m = re.search(r'const CACHE_VERSION = "([^"]+)"', body)
    return m.group(1) if m else ""


if __name__ == "__main__":
    main()
