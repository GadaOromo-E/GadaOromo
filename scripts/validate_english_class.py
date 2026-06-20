#!/usr/bin/env python3
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data", "english-class")

fps = set()
issues = []
total = 0

for path in sorted(glob.glob(os.path.join(DATA, "*.json"))):
    if path.endswith("index.json"):
        continue
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    for cat in data["categories"]:
        for les in cat["lessons"]:
            total += 1
            dlg = les["dialogue"]
            fp = "|".join(l["text"] for l in dlg)
            if fp in fps:
                issues.append("duplicate: " + les["id"])
            fps.add(fp)
            if not (12 <= len(dlg) <= 20):
                issues.append(f"lines {len(dlg)}: {les['id']}")
            if len(les.get("vocabulary", [])) != 5:
                issues.append(f"vocab count: {les['id']}")
            if len(les.get("quiz", [])) != 5:
                issues.append(f"quiz count: {les['id']}")

with open(os.path.join(DATA, "index.json"), encoding="utf-8") as f:
    idx = json.load(f)

print("total lessons:", total)
print("index stats:", idx["stats"])
print("unique dialogues:", len(fps))
print("issues:", len(issues))
if issues:
    for i in issues[:10]:
        print(" -", i)
    sys.exit(1)
print("OK")
