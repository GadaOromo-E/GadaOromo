#!/usr/bin/env python3
"""Verify production Railway deployment includes latest English Class build."""
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = (os.environ.get("VERIFY_BASE_URL") or "https://gadaadictionary.com").rstrip("/")
PRODUCTION_SITE_URLS = (
    "https://gadaadictionary.com",
    "https://www.gadaadictionary.com",
)
MAIN_SHA = (os.environ.get("GITHUB_MAIN_SHA") or "").strip()


def _read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _sha256_text(text):
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _fetch(url, timeout=45):
    req = urllib.request.Request(url, headers={"User-Agent": "gadaa-deploy-verify/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read()
        return {
            "url": url,
            "status": int(resp.status),
            "headers": {k: v for k, v in resp.headers.items()},
            "text": body.decode("utf-8", "replace"),
            "bytes": len(body),
        }


def _git_main_sha():
    if MAIN_SHA:
        return MAIN_SHA
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "origin/main"],
            cwd=ROOT,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return out.strip()
    except Exception:
        return ""


def _local_fingerprints():
    ec_html = _read(os.path.join(ROOT, "templates", "english_class.html"))
    ec_js = _read(os.path.join(ROOT, "static", "english-class.js"))
    index_html = _read(os.path.join(ROOT, "templates", "index.html"))
    return {
        "main_sha": _git_main_sha(),
        "english_class_html_sha256": _sha256_text(ec_html),
        "english_class_js_sha256": _sha256_text(ec_js),
        "markers": {
            "sidebar_learn_languages": "🌍 Learn Languages" in index_html,
            "sidebar_english_class": "🎓 English Class" in index_html,
            "ec_view_hidden": "ec-view-hidden" in ec_html,
            "ec_level_card": "ec-level-card" in ec_html,
            "ec_home_id": 'id="ecHome"' in ec_html,
            "english_class_js_show_view": "function showView(name)" in ec_js,
            "english_class_api_path": "/api/english-class/" in ec_js,
        },
    }


def verify():
    local = _local_fingerprints()
    report = {
        "base_url": BASE,
        "github_main_sha": local["main_sha"],
        "checks": {},
        "mismatches": [],
        "summary": "unknown",
    }

    endpoints = {
        "english_class_page": f"{BASE}/english-class",
        "english_class_js": f"{BASE}/static/english-class.js",
        "index_page": f"{BASE}/",
        "english_class_api_a1": f"{BASE}/api/english-class/a1",
    }

    fetched = {}
    for key, url in endpoints.items():
        try:
            fetched[key] = _fetch(url)
        except urllib.error.HTTPError as e:
            fetched[key] = {
                "url": url,
                "status": int(e.code),
                "headers": {k: v for k, v in (e.headers.items() if e.headers else [])},
                "text": (e.read() or b"").decode("utf-8", "replace"),
                "bytes": 0,
                "error": repr(e),
            }
        except Exception as e:
            fetched[key] = {"url": url, "status": None, "error": repr(e), "text": "", "headers": {}}

    ec_page = fetched.get("english_class_page") or {}
    ec_js = fetched.get("english_class_js") or {}
    index_page = fetched.get("index_page") or {}
    api_a1 = fetched.get("english_class_api_a1") or {}

    deployed_build = (
        (ec_page.get("headers") or {}).get("X-Gadaa-Build")
        or (index_page.get("headers") or {}).get("X-Gadaa-Build")
        or ""
    ).strip()

    report["deployed_build_token"] = deployed_build
    report["deployed_commit_prefix_match"] = bool(
        local["main_sha"] and deployed_build and local["main_sha"].startswith(deployed_build)
    )

    # 1-2: template/static presence via HTTP (what container actually serves)
    report["checks"]["english_class_route_200"] = ec_page.get("status") == 200
    report["checks"]["english_class_js_200"] = ec_js.get("status") == 200
    report["checks"]["english_class_api_200"] = api_a1.get("status") == 200

    ec_html_live = ec_page.get("text") or ""
    ec_js_live = ec_js.get("text") or ""
    index_live = index_page.get("text") or ""

    report["checks"]["deployed_has_ec_view_hidden"] = "ec-view-hidden" in ec_html_live
    report["checks"]["deployed_has_ec_level_card"] = "ec-level-card" in ec_html_live
    report["checks"]["deployed_has_ec_home"] = 'id="ecHome"' in ec_html_live
    report["checks"]["deployed_has_english_class_js_ref"] = "english-class.js" in ec_html_live
    report["checks"]["deployed_js_has_show_view"] = "function showView(name)" in ec_js_live
    report["checks"]["deployed_js_has_api_path"] = "/api/english-class/" in ec_js_live

    # 3: sidebar on deployed index
    report["checks"]["deployed_sidebar_learn_languages"] = "🌍 Learn Languages" in index_live
    report["checks"]["deployed_sidebar_english_class"] = "🎓 English Class" in index_live
    report["checks"]["deployed_sidebar_old_learn_label"] = ">🎓 Learn</a>" in index_live or 'href="/learn">🎓 Learn<' in index_live

    # 5: markup fingerprint compare (hash of key sections)
    report["deployed_english_class_html_sha256"] = _sha256_text(ec_html_live)
    report["deployed_english_class_js_sha256"] = _sha256_text(ec_js_live)
    report["checks"]["english_class_html_hash_match"] = (
        report["deployed_english_class_html_sha256"] == local["english_class_html_sha256"]
    )
    report["checks"]["english_class_js_hash_match"] = (
        report["deployed_english_class_js_sha256"] == local["english_class_js_sha256"]
    )

    # Note: rendered HTML != template file hash; compare markers instead
    marker_checks = [
        "deployed_has_ec_view_hidden",
        "deployed_has_ec_level_card",
        "deployed_has_ec_home",
        "deployed_has_english_class_js_ref",
        "deployed_js_has_show_view",
        "deployed_js_has_api_path",
        "deployed_sidebar_learn_languages",
        "deployed_sidebar_english_class",
        "english_class_route_200",
        "english_class_js_200",
        "english_class_api_200",
    ]
    for name in marker_checks:
        if not report["checks"].get(name):
            report["mismatches"].append(name)

    if local["main_sha"] and deployed_build and not report["deployed_commit_prefix_match"]:
        report["mismatches"].append("deployed_commit_sha_mismatch")

    if report["checks"].get("deployed_sidebar_old_learn_label"):
        report["mismatches"].append("deployed_sidebar_still_uses_old_learn_label")

    if not report["mismatches"]:
        report["summary"] = "match"
    elif any(
        x in report["mismatches"]
        for x in (
            "english_class_route_200",
            "english_class_js_200",
            "deployed_has_ec_view_hidden",
            "deployed_sidebar_english_class",
        )
    ):
        report["summary"] = "major_mismatch"
    else:
        report["summary"] = "partial_mismatch"

    report["local"] = local
    report["response_sizes"] = {
        k: {"status": (fetched[k].get("status")), "bytes": fetched[k].get("bytes")}
        for k in fetched
    }
    return report


if __name__ == "__main__":
    print(json.dumps(verify(), indent=2))
