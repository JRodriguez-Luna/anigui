"""Temporary CI probe (removed in the next commit)."""
import json, sys
sys.path.insert(0, ".")
from core import http
q = "{ MediaTagCollection { name category isAdult } }"
r = http.request("https://graphql.anilist.co", data=json.dumps({"query": q}).encode(),
                 headers={"Content-Type": "application/json", "Accept": "application/json"}, timeout=20)
tags = json.loads(r.body)["data"]["MediaTagCollection"]
hits = [t for t in tags if any(w in t["name"].lower() for w in ("christ", "holiday", "winter", "snow", "santa", "new year"))]
print(f"::notice title=probe::{len(tags)} tags; matches: {hits}")
