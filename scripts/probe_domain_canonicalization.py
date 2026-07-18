#!/usr/bin/env python3
"""Verify canonical apex domain responses for Gadaa (https://gadaadictionary.com)."""
import json
import re
import urllib.error
import urllib.request

DNS_GOOGLE = "https://dns.google/resolve"
CANONICAL_BASE = "https://gadaadictionary.com"

HOSTS = [
    CANONICAL_BASE,
    "http://gadaadictionary.com",
]
PATHS = ["/", "/english-class", "/service-worker.js", "/learn"]


def fetch(url, follow=True, timeout=45):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "gadaa-domain-probe/1.0", "Cache-Control": "no-cache"},
        method="GET",
    )
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    if follow:
        opener = urllib.request.build_opener()
    else:
        opener = urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(req, timeout=timeout) as resp:
            body = resp.read(120000).decode("utf-8", "replace")
            return {
                "url": url,
                "final_url": resp.geturl(),
                "status": int(resp.status),
                "headers": {k: v for k, v in resp.headers.items()},
                "body_len": len(body),
                "body": body,
                "error": None,
            }
    except urllib.error.HTTPError as e:
        body = (e.read() or b"")[:120000].decode("utf-8", "replace")
        return {
            "url": url,
            "final_url": e.geturl() if hasattr(e, "geturl") else url,
            "status": int(e.code),
            "headers": {k: v for k, v in (e.headers.items() if e.headers else [])},
            "body_len": len(body),
            "body": body,
            "error": None,
        }
    except Exception as e:
        return {"url": url, "error": repr(e)}


def summarize_html(body):
    return {
        "learn_languages": "🌍 Learn Languages" in body,
        "english_class": "🎓 English Class" in body,
        "build_meta": _meta(body, "gadaa-build-token"),
        "sw_canonical": _meta(body, "gadaa-sw-canonical-url"),
        "canonical_link": _canonical(body),
    }


def _meta(html, name):
    m = re.search(rf'<meta\s+name="{re.escape(name)}"\s+content="([^"]*)"', html, re.I)
    return m.group(1) if m else ""


def _canonical(html):
    m = re.search(r'<link\s+rel="canonical"\s+href="([^"]*)"', html, re.I)
    return m.group(1) if m else ""


def dns_lookup(name, rtype):
    url = f"{DNS_GOOGLE}?name={name}&type={rtype}"
    try:
        with urllib.request.urlopen(url, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        answers = [
            {"name": a.get("name"), "type": a.get("type"), "ttl": a.get("TTL"), "data": a.get("data")}
            for a in (data.get("Answer") or [])
        ]
        return {"status": data.get("Status"), "answers": answers, "error": None}
    except Exception as e:
        return {"status": None, "answers": [], "error": repr(e)}


def main():
    report = {
        "canonical_base": CANONICAL_BASE,
        "dns": {
            "apex_a": dns_lookup("gadaadictionary.com", "A"),
            "apex_aaaa": dns_lookup("gadaadictionary.com", "AAAA"),
            "apex_cname": dns_lookup("gadaadictionary.com", "CNAME"),
            "acme_txt": dns_lookup("_acme-challenge.gadaadictionary.com", "TXT"),
        },
        "hosts": {},
        "redirects_no_follow": [],
        "comparison": {},
    }

    for base in HOSTS:
        for path in PATHS:
            url = base + path
            no_follow = fetch(url, follow=False)
            report["redirects_no_follow"].append(
                {
                    "url": url,
                    "status": no_follow.get("status"),
                    "location": no_follow.get("headers", {}).get("Location")
                    or no_follow.get("headers", {}).get("location"),
                    "error": no_follow.get("error"),
                }
            )

    host_report = {}
    for path in PATHS:
        url = CANONICAL_BASE + path
        res = fetch(url, follow=True)
        entry = {
            "status": res.get("status"),
            "final_url": res.get("final_url"),
            "error": res.get("error"),
            "x_gadaa_build": (res.get("headers") or {}).get("X-Gadaa-Build")
            or (res.get("headers") or {}).get("x-gadaa-build"),
            "server": (res.get("headers") or {}).get("Server"),
            "cf_ray": (res.get("headers") or {}).get("CF-RAY"),
            "cache_control": (res.get("headers") or {}).get("Cache-Control"),
        }
        if path in ("/", "/english-class") and res.get("body"):
            entry.update(summarize_html(res["body"]))
        if path == "/service-worker.js" and res.get("body"):
            m = re.search(r'const CACHE_VERSION = "([^"]+)"', res["body"])
            entry["sw_cache_version"] = m.group(1) if m else ""
        host_report[path] = entry
    report["hosts"][CANONICAL_BASE] = host_report

    apex = report["hosts"].get(CANONICAL_BASE, {}).get("/", {})
    canonical_link = apex.get("canonical_link") or ""
    report["comparison"] = {
        "canonical_base": CANONICAL_BASE,
        "homepage_build_meta": apex.get("build_meta"),
        "homepage_sidebar": {
            "learn_languages": apex.get("learn_languages"),
            "english_class": apex.get("english_class"),
        },
        "canonical_link": canonical_link,
        "canonical_link_uses_apex": canonical_link.startswith(CANONICAL_BASE),
        "sw_cache_version": report["hosts"]
        .get(CANONICAL_BASE, {})
        .get("/service-worker.js", {})
        .get("sw_cache_version"),
    }

    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
