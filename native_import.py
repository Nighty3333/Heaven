"""Import in-process WinHTTP captures into the Team Trials pipeline.

The native Heaven overlay (heaven_overlay.dll) taps the game's WinHTTP read path
and appends every /umamusume/ request+response to data/native_capture.jsonl as
  { "ts", "path", "req"(base64 raw bytes), "resp"(base64 raw bytes) }

This module decodes each response with decoder.py (auto-detecting the udid from
the request body, exactly like the mitmproxy addon) and appends the decoded
payloads to raw_full.jsonl in the SAME format discover_addon produces — so the
existing tt_analyze.py turns them into team_trials_history.jsonl unchanged.

No proxy, no certificate: the capture happens inside the game process, so this
works whenever the game is running and the overlay's "Team Trials" capture is on.
"""
from __future__ import annotations

import base64
import json
import struct
import time
from pathlib import Path

import decoder

DATA = Path(__file__).parent / "data"
NATIVE_PATH = DATA / "native_capture.jsonl"
CURSOR_PATH = DATA / "native_capture.cursor"
RAW_FULL = DATA / "raw_full.jsonl"
MARKER = "/umamusume/"


def _endpoint(path: str) -> str | None:
    i = path.find(MARKER)
    if i < 0:
        return None
    ep = path[i + len(MARKER):]
    q = ep.find("?")
    return ep[:q] if q >= 0 else ep


def _udids_from_request(content: bytes) -> list[str]:
    """udid is embedded in the request's binary header (16 bytes at a fixed
    offset before the first blob's end). Mirrors discover_addon."""
    out: list[str] = []
    raws: list[bytes] = []
    try:
        raws.append(base64.b64decode(content.decode("ascii", errors="strict").strip()))
    except Exception:
        pass
    raws.append(content)
    for raw in raws:
        if len(raw) < 4:
            continue
        try:
            hlen = struct.unpack("<I", raw[:4])[0]
        except Exception:
            continue
        blob1_end = 4 + hlen
        if hlen < 64 or blob1_end > len(raw):
            continue
        for off in (96, 48):
            start = blob1_end - off
            if start < 0 or start + 16 > len(raw):
                continue
            udid_hex = raw[start:start + 16].hex()
            if len(udid_hex) == 32 and udid_hex not in out:
                out.append(udid_hex)
    return out


def import_native() -> dict:
    """Decode any new native_capture lines into raw_full.jsonl. Tracks a byte
    cursor so re-runs only process new captures. Returns counts."""
    if not NATIVE_PATH.exists():
        return {"ok": False, "error": "no native_capture.jsonl yet — enable "
                "'Team Trials' capture in the in-game overlay and play a match."}

    try:
        start = int(CURSOR_PATH.read_text().strip())
    except Exception:
        start = 0
    size = NATIVE_PATH.stat().st_size
    if start > size:            # file was rotated/cleared
        start = 0

    udid = decoder.load_udid()
    lines = decoded = udid_tries = 0
    out: list[dict] = []

    with open(NATIVE_PATH, "r", encoding="utf-8") as f:
        f.seek(start)
        for line in f:
            line = line.strip()
            if not line:
                continue
            lines += 1
            try:
                e = json.loads(line)
            except Exception:
                continue
            ep = _endpoint(e.get("path", ""))
            if not ep:
                continue
            try:
                resp = base64.b64decode(e.get("resp", ""))
            except Exception:
                continue
            try:
                req = base64.b64decode(e.get("req", "")) if e.get("req") else b""
            except Exception:
                req = b""

            dec = None
            if udid:
                try:
                    dec = decoder.decode_response_body(resp, udid)
                except Exception:
                    dec = None
            if dec is None and req:
                for cand in _udids_from_request(req):
                    udid_tries += 1
                    try:
                        dec = decoder.decode_response_body(resp, cand)
                    except Exception:
                        dec = None
                    if dec is not None:
                        udid = cand
                        decoder.save_udid(udid)
                        break
            if dec is None:
                continue

            out.append({
                "ts": e.get("ts") or time.time(),
                "endpoint": ep,
                "size": len(resp),
                "payload": dec,
            })
            decoded += 1

    if out:
        RAW_FULL.parent.mkdir(parents=True, exist_ok=True)
        with open(RAW_FULL, "a", encoding="utf-8") as rf:
            for rec in out:
                rf.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")

    CURSOR_PATH.write_text(str(size))
    return {"ok": True, "lines": lines, "decoded": decoded, "udid_tries": udid_tries}


if __name__ == "__main__":
    print(import_native())
