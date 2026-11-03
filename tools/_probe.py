"""Temporary CI probe (removed in the next commit)."""
import os, re, subprocess, sys
sys.path.insert(0, ".")
def note(m): print(f"::notice title=probe::{m}"[:3000])
os.makedirs("/tmp/stub", exist_ok=True)
open("/tmp/stub/fzf", "w").write("#!/bin/sh\nhead -n 1\n")
os.chmod("/tmp/stub/fzf", 0o755)
env = {**os.environ, "ANI_CLI_PLAYER": "debug", "ANI_CLI_HIST_DIR": "/tmp/h", "PATH": "/tmp/stub:" + os.environ["PATH"], "TERM": "dumb"}
for query in ("my hero academia season 5", "my hero academia season 6"):
    for ep in ("1", "2", "3"):
        res = {}
        for mode in ("sub", "dub"):
            args = ["ani-cli", "-S", "1", "-e", ep] + (["--dub"] if mode == "dub" else []) + [query]
            out = subprocess.run(args, capture_output=True, text=True, timeout=120, env=env).stdout
            m = re.search(r"Selected link:\s*(\S+)", out)
            res[mode] = m.group(1) if m else "-"
            q = re.findall(r"^(\d{3,4}) >", out, re.M)
            res[mode + "_q"] = q
        same = res["sub"].rsplit("/", 2)[0] == res["dub"].rsplit("/", 2)[0]
        note(f"{query} ep {ep}: SAME={same} sub={res['sub']} {res['sub_q']} | dub={res['dub']} {res['dub_q']}")
        if ep == "1":
            # what the dub master playlist says about audio
            master = res["dub"].rsplit("/", 2)[0] + "/master.m3u8"
            for url in (res["dub"],):
                p = subprocess.run(["curl", "-sL", "-m", "20", "-e", "https://zokoanime.example/", url], capture_output=True, text=True)
                note(f"  dub playlist head: {p.stdout[:300]!r}")
