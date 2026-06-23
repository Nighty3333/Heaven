"""Skill activation stats from horseACT race dumps (heaven-races).

The in-game race exporter writes one JSON per race under
    <game>/heaven-races/<RaceType>/<...>.json
in horseACT/Hakuraku format (C# `<X>k__BackingField` fields). Each file holds
the full RaceInfo incl. the player horse's owned skills + the base64(gzip())
race simulation, which `tt_scenario` decodes into per-horse skill activations.

This module walks those files (incrementally) and, for the PLAYER's horse,
records one row per race:
    {chara_id, chara_name, running_style, distance_cat, owned_skills, activated_skills}
into `race_skill_history.jsonl`. Skill Lookup reads these rows (alongside the
Team Trials history) and can filter by running style and distance.

Career races give one data point each (only the player's horse is in the
dump's PlayerTeamMemberArray), but there are tens of thousands of them.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import tt_scenario

# heaven-races lives next to the game exe.
_GAME_DIR = Path(os.environ.get(
    "HEAVEN_RACES_DIR",
    r"D:\Steam\steamapps\common\UmamusumePrettyDerby\heaven-races",
))

try:
    import safe_store
    _DATA_DIR = safe_store.ensure_migrated()
except Exception:
    _DATA_DIR = Path(__file__).parent / "data"

ROWS_PATH = _DATA_DIR / "race_skill_history.jsonl"
SEEN_PATH = _DATA_DIR / "race_skill_seen.txt"
# Imported community exports land here (one .jsonl per shared file). They're
# merged into the pool and deduped by (race_id, chara_id) at load time.
COMMUNITY_DIR = _DATA_DIR / "race_skill_community"
# A community seed shipped IN the repo (so everyone gets it on update). It's
# merged into the pool deduped by (race_id, chara_id) — it ADDS to your own
# data, never replaces it (and is a no-op for whoever contributed it).
SEED_PATH = Path(__file__).parent / "seed" / "community_skill_seed.jsonl"

B = ">k__BackingField"
_RS = {1: "NIGE", 2: "SENKO", 3: "SASHI", 4: "OIKOMI"}
_DIST = {"short": "sprint", "sprint": "sprint", "mile": "mile",
         "medium": "medium", "middle": "medium", "long": "long"}
# Team Trials distance_type (int 1-5) -> canonical bucket.
_TT_DIST = {1: "sprint", 2: "mile", 3: "medium", 4: "long", 5: "dirt"}

try:
    import master as _master
except Exception:
    _master = None


def _g(o: dict, key: str):
    return o.get("<" + key + B)


def _dist_cat(course_dist_type, ground) -> str:
    if ground == 2:          # dirt surface collapses into its own bucket
        return "dirt"
    return _DIST.get(str(course_dist_type).lower(), str(course_dist_type).lower())


def _extract_rows(obj: dict) -> list[dict]:
    """One row per the player's horse(s) in a race dump. Career = 1 horse;
    Champions / Room match = the player's whole team (each fully trained).
    PlayerTeamMemberArray holds only the player's horses (opponents/NPCs aren't
    in it), so every entry is yours."""
    horses = _g(obj, "PlayerTeamMemberArray") or []
    if not horses:
        return []

    # Parse the race sim once → activations keyed by sim horse index.
    acts_by_idx: dict = {}
    sim = _g(obj, "SimDataBase64")
    if sim:
        try:
            acts_by_idx = tt_scenario.activations_per_horse(tt_scenario.parse(sim))
        except Exception:
            acts_by_idx = {}

    rcs = _g(obj, "RaceCourseSet") or {}
    dist_cat = _dist_cat(_g(obj, "CourseDistanceType"), rcs.get("Ground"))
    # RandomSeed is unique per race → with chara_id it's a global dedup key so
    # merging community data never double-counts the same race/uma.
    race_id = _g(obj, "RandomSeed")

    out: list[dict] = []
    for horse in horses:
        rhd = horse.get("_responseHorseData") or {}
        owned = [s.get("skill_id") for s in (rhd.get("skill_array") or []) if s.get("skill_id")]
        if not owned:
            continue
        out.append({
            "race_id":         race_id,
            "chara_id":        rhd.get("card_id"),
            "chara_name":      _g(horse, "charaName") or "?",
            "running_style":   _RS.get(rhd.get("running_style"), str(rhd.get("running_style"))),
            "distance_cat":    dist_cat,
            "owned_skills":    owned,
            "activated_skills": acts_by_idx.get(horse.get("horseIndex"), []),
            "src":             "race",
        })
    return out


def _extract_rows_tt(obj: dict) -> list[dict]:
    """Team Trials dump (raw team_stadium response, snake_case). Each race has a
    `race_result_array` + `race_start_params_array`; the latter carries every
    horse's skill_array. A TT race fields 12 horses — 6 real player/opponent umas
    (card_id > 0) and 6 filler mobs (card_id 0, skipped). All real ones are
    recorded, so a single TT dump yields skill data for many umas."""
    rr = obj.get("race_result_array") or []
    rsp = obj.get("race_start_params_array") or []
    hd_by_round, seed_by_round = {}, {}
    for p in rsp:
        hd_by_round[p.get("round")] = p.get("race_horse_data_array") or []
        seed_by_round[p.get("round")] = p.get("random_seed")

    out: list[dict] = []
    for race in rr:
        rnd = race.get("round")
        dist_cat = _TT_DIST.get(race.get("distance_type"))
        seed = seed_by_round.get(rnd)
        # sim horse index = position in chara_result_array (the index the
        # race_scenario events key per-horse data on).
        sim_idx = {cr.get("trained_chara_id"): i
                   for i, cr in enumerate(race.get("chara_result_array") or [])}
        acts = {}
        scen = race.get("race_scenario")
        if scen:
            try:
                acts = tt_scenario.activations_per_horse(tt_scenario.parse(scen))
            except Exception:
                acts = {}
        for hd in hd_by_round.get(rnd, []):
            cid = hd.get("card_id")
            if not cid:                      # filler mob (card_id 0) → skip
                continue
            owned = [s.get("skill_id") for s in (hd.get("skill_array") or []) if s.get("skill_id")]
            if not owned:
                continue
            hi = sim_idx.get(hd.get("trained_chara_id"))
            out.append({
                "race_id":         seed,
                "chara_id":        cid,
                "chara_name":      (_master.chara_name_by_card_id(cid) if _master else None) or "?",
                "running_style":   _RS.get(hd.get("running_style"), str(hd.get("running_style"))),
                "distance_cat":    dist_cat,
                "owned_skills":    owned,
                "activated_skills": acts.get(hi, []) if hi is not None else [],
                "src":             "tt",
            })
    return out


def _extract_any(obj: dict) -> list[dict]:
    """Dispatch on dump shape: horseACT race (PlayerTeamMemberArray) vs Team
    Trials (race_result_array)."""
    if _g(obj, "PlayerTeamMemberArray") is not None:
        return _extract_rows(obj)
    if obj.get("race_result_array") is not None:
        return _extract_rows_tt(obj)
    return []


def _load_seen() -> set[str]:
    if not SEEN_PATH.exists():
        return set()
    return set(SEEN_PATH.read_text(encoding="utf-8").splitlines())


def import_races(types: tuple[str, ...] = ("Career",), limit: int | None = None,
                 flush_every: int = 500) -> dict:
    """Incrementally parse new race dumps and append their skill rows.
    `types` = subfolders of heaven-races to scan. Returns counts."""
    if not _GAME_DIR.exists():
        return {"ok": False, "error": f"heaven-races not found: {_GAME_DIR}"}

    seen = _load_seen()
    _DATA_DIR.mkdir(parents=True, exist_ok=True)

    files: list[Path] = []
    for t in types:
        d = _GAME_DIR / t
        if d.exists():
            files.extend(d.glob("*.json"))
    todo = [f for f in files if f.name not in seen]
    if limit:
        todo = todo[:limit]

    new_rows: list[dict] = []
    new_seen: list[str] = []
    processed = 0
    errors = 0

    def _flush():
        nonlocal new_rows, new_seen
        if new_rows:
            with open(ROWS_PATH, "a", encoding="utf-8") as f:
                for r in new_rows:
                    f.write(json.dumps(r, separators=(",", ":"), default=str) + "\n")
        if new_seen:
            with open(SEEN_PATH, "a", encoding="utf-8") as f:
                f.write("\n".join(new_seen) + "\n")
        new_rows, new_seen = [], []

    for fp in todo:
        try:
            obj = json.loads(fp.read_text(encoding="utf-8"))
            new_rows.extend(_extract_any(obj))
        except Exception:
            errors += 1
        new_seen.append(fp.name)
        processed += 1
        if processed % flush_every == 0:
            _flush()
    _flush()

    total_rows = sum(1 for _ in open(ROWS_PATH, encoding="utf-8")) if ROWS_PATH.exists() else 0
    return {"ok": True, "processed": processed, "errors": errors,
            "remaining": len(files) - len(seen) - processed, "total_rows": total_rows}


def load_rows() -> list[dict]:
    """Your own race rows + any imported community files, MERGED and DEDUPED by
    (race_id, chara_id) so the same race/uma never counts twice (even across
    people or re-imports)."""
    out: list[dict] = []
    seen: set = set()
    paths = [ROWS_PATH, SEED_PATH]          # your own first, then the bundled seed
    if COMMUNITY_DIR.exists():
        paths += sorted(COMMUNITY_DIR.glob("*.jsonl"))
    for p in paths:
        if not p.exists():
            continue
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                rid = r.get("race_id")
                if rid is not None:
                    key = (rid, r.get("chara_id"))
                    if key in seen:
                        continue
                    seen.add(key)
                out.append(r)
    return out


def import_community_file(src_bytes: bytes, label: str = "shared") -> dict:
    """Save an uploaded community export under COMMUNITY_DIR (so load_rows merges
    + dedupes it). Re-importing the same label overwrites, so it never piles up.
    Returns how many NEW (race_id, chara_id) pairs it adds over what we have."""
    COMMUNITY_DIR.mkdir(parents=True, exist_ok=True)
    safe = "".join(c for c in label if c.isalnum() or c in "-_") or "shared"
    have = {(r.get("race_id"), r.get("chara_id")) for r in load_rows()
            if r.get("race_id") is not None}
    added = 0
    rows_in = 0
    rejected = 0                 # rows we WON'T keep (no race_id → can't dedup)
    valid_lines: list[str] = []  # only keep dedup-able, well-formed rows
    for line in src_bytes.decode("utf-8", "ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:
            rejected += 1
            continue
        rows_in += 1
        # require race_id + owned_skills, else it can't be deduped or counted
        if r.get("race_id") is None or not r.get("owned_skills"):
            rejected += 1
            continue
        valid_lines.append(json.dumps(r, separators=(",", ":"), default=str))
        k = (r.get("race_id"), r.get("chara_id"))
        if k not in have:
            have.add(k)
            added += 1
    if not valid_lines:
        return {"ok": False, "error": "no valid rows (need race_id + owned_skills) — "
                "is this a Heaven skill-data export?"}
    (COMMUNITY_DIR / f"{safe}.jsonl").write_text("\n".join(valid_lines) + "\n", encoding="utf-8")
    return {"ok": True, "rows_in_file": rows_in, "new_added": added, "rejected": rejected,
            "duplicates": rows_in - added - rejected if rows_in >= added + rejected else 0}


if __name__ == "__main__":
    import sys
    types = tuple(sys.argv[1:]) or ("Career",)
    print(import_races(types))
