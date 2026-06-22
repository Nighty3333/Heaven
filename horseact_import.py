"""Import ayaliz/horseACT-format Team Trials JSONs into the dashboard history.

A horseACT dump is a full reflection of the game's `TeamStadiumResult` object —
the same schema Heaven's `race_export.rs` writes to
`heaven-races/Team trials/TT-*.json`, and the schema ayaliz/horseACT and Hakuraku
use. It is NOT the dashboard's compact native capture, so the normal
`htt_import` / `/api/db/import` (Heaven bundle) paths reject it.

This module maps a horseACT dump onto the SAME compact per-trial shape that
`htt_import._rows_for_trial` consumes, then reuses that to emit identical history
rows. Where the data lives in a horseACT dump:

  * rich per-uma profile (stats, owned skills, card/chara id, running style) →
        race_start_params_array[i].race_horse_data_array[]
  * per-uma race outcome (finish order/time, gate) →
        race_result_array[i].chara_result_array[]
  * the two are cross-referenced by `trained_chara_id`.
  * YOUR team is `team_id == 1`; the scenario horse index is the position in
        `chara_result_array` (gate order), same as the native path.

`race_result_array[i]` and `race_start_params_array[i]` are parallel (both one
entry per round, aligned by `round`).
"""
from __future__ import annotations

import json
from pathlib import Path

import htt_import

# In a Team Trials result, your own team's horses carry team_id == 1
# (opponent == 2, NPC filler == 0). Matches htt.rs's native targeted read.
MY_TEAM_ID = 1


def is_horseact(doc) -> bool:
    """True if `doc` looks like a horseACT / TeamStadiumResult dump (vs a Heaven
    export bundle or the compact native capture)."""
    return (
        isinstance(doc, dict)
        and isinstance(doc.get("race_result_array"), list)
        and ("race_start_params_array" in doc or "horseACT_version" in doc)
    )


def _display_score(cr: dict):
    """Best-effort per-uma displayed score from the chara_result `score_array`
    (raw scores + bonuses). Returns 0 if the structure isn't as expected — this
    field is only used for display/dedup, and finish_time already discriminates
    genuinely different runs."""
    total = 0
    try:
        for entry in cr.get("score_array") or []:
            rs = entry.get("raw_score")
            if isinstance(rs, (int, float)):
                total += rs
            for b in entry.get("bonus_array") or []:
                bs = b.get("bonus_score")
                if isinstance(bs, (int, float)):
                    total += bs
    except Exception:
        return 0
    return total


def _trial_id(doc: dict, fallback: str) -> str:
    """Stable, per-trial id. `race_instance_id` is unique per real race, so the
    first round's id uniquely identifies the trial and survives re-imports (same
    file → same id → deduped), while distinct trials never collide. Falls back to
    the source filename stem."""
    for rsp in doc.get("race_start_params_array") or []:
        if isinstance(rsp, dict) and rsp.get("race_instance_id"):
            return f"ha_{rsp['race_instance_id']}"
    return f"ha_{fallback}"


def to_compact_trial(doc: dict, trial_id: str) -> dict:
    """Map a horseACT dump → the compact per-trial dict htt_import consumes."""
    rra = doc.get("race_result_array") or []
    rspa = doc.get("race_start_params_array") or []
    rspa_by_round = {r.get("round"): r for r in rspa if isinstance(r, dict)}

    races: list[dict] = []
    for idx, race in enumerate(rra):
        if not isinstance(race, dict):
            continue
        rnd = race.get("round")
        rsp = rspa_by_round.get(rnd) or (rspa[idx] if idx < len(rspa) else {})
        rhd = (rsp or {}).get("race_horse_data_array") or []
        rhd_by_tcid = {c.get("trained_chara_id"): c for c in rhd if isinstance(c, dict)}

        charas: list[dict] = []
        for hidx, cr in enumerate(race.get("chara_result_array") or []):
            if not isinstance(cr, dict) or cr.get("team_id") != MY_TEAM_ID:
                continue
            tcid = cr.get("trained_chara_id")
            prof = rhd_by_tcid.get(tcid, {})
            owned = [
                s.get("skill_id")
                for s in (prof.get("skill_array") or [])
                if isinstance(s, dict) and s.get("skill_id")
            ]
            charas.append({
                "horse_idx":        hidx,           # gate order == scenario horse index
                "trained_chara_id": tcid,
                "card_id":          prof.get("card_id"),
                "chara_id":         prof.get("chara_id"),
                "speed":            prof.get("speed"),
                "stamina":          prof.get("stamina"),
                "power":            prof.get("pow"),   # horseACT names it `pow`
                "guts":             prof.get("guts"),
                "wiz":              prof.get("wiz"),
                "running_style":    prof.get("running_style"),
                "finish_order":     cr.get("finish_order"),
                "finish_time":      cr.get("finish_time"),
                "display_score":    _display_score(cr),
                "owned_skills":     owned,
                "frame_order":      cr.get("frame_order"),
            })

        races.append({
            "race_idx":         idx,
            "round":            rnd,
            "distance_type":    race.get("distance_type"),
            "team_total_score": race.get("team_total_score") or 0,
            "race_scenario":    race.get("race_scenario"),
            # stadium fields (parallel to the native capture) for stadium_tracker reuse
            "race_instance_id": (rsp or {}).get("race_instance_id"),
            "weather":          (rsp or {}).get("weather"),
            "ground_condition": (rsp or {}).get("ground_condition"),
            "season":           (rsp or {}).get("season"),
            "random_seed":      (rsp or {}).get("random_seed"),
            "charas":           charas,
        })

    return {
        "trial_id":           trial_id,
        "captured_ms":        0,
        "support_card_bonus": doc.get("support_card_bonus") or 0,
        "races":              races,
    }


def rows_from_doc(doc: dict, source_name: str = "") -> list[dict]:
    """horseACT dump → dashboard history rows (identical schema to native capture).
    Reuses htt_import._rows_for_trial so skill activations/scores come from the
    same race_scenario parser the native path uses."""
    stem = Path(source_name).stem if source_name else "unknown"
    trial = to_compact_trial(doc, _trial_id(doc, stem))
    return htt_import._rows_for_trial(trial)


def stadium_payloads_from_doc(doc: dict) -> list[dict]:
    """Rebuild the `team_stadium/start` payload stadium_tracker expects, from the
    horseACT `race_start_params_array` (Track & Condition observations). My gates
    get viewer_id 1 (team_id == 1); everyone else 0. Empty if no stadium fields."""
    rounds: list[dict] = []
    for rsp in doc.get("race_start_params_array") or []:
        if not isinstance(rsp, dict) or rsp.get("race_instance_id") is None:
            continue
        rounds.append({
            "round":            rsp.get("round"),
            "race_instance_id": rsp.get("race_instance_id"),
            "weather":          rsp.get("weather"),
            "ground_condition": rsp.get("ground_condition"),
            "season":           rsp.get("season"),
            "random_seed":      rsp.get("random_seed"),
            "race_horse_data_array": [
                {
                    "trained_chara_id": c.get("trained_chara_id"),
                    "chara_id":         c.get("chara_id"),
                    "card_id":          c.get("card_id"),
                    "running_style":    c.get("running_style"),
                    "frame_order":      c.get("frame_order"),
                    "viewer_id":        1 if c.get("team_id") == MY_TEAM_ID else 0,
                }
                for c in (rsp.get("race_horse_data_array") or [])
                if isinstance(c, dict)
            ],
        })
    if not rounds:
        return []
    return [{"endpoint": "team_stadium/start",
             "payload": {"race_start_params_array": rounds}}]


# ── CLI: import a folder (or files) of horseACT TT JSONs into history ──────────
def import_paths(paths: "list[Path]") -> dict:
    """Import a list of horseACT JSON files into history (deduped). Returns a
    summary dict. Stadium observations are ingested best-effort."""
    import jsonl_util

    history = htt_import.HISTORY_PATH
    seen = htt_import._existing_keys()
    new_rows: list[dict] = []
    files_ok = parse_errors = not_horseact = 0
    stad_payloads: list[dict] = []

    for fp in paths:
        try:
            doc = json.loads(Path(fp).read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  ! could not read {fp}: {e}")
            parse_errors += 1
            continue
        if not is_horseact(doc):
            not_horseact += 1
            continue
        files_ok += 1
        for row in rows_from_doc(doc, str(fp)):
            key = htt_import._row_key(row)
            if key in seen:
                continue
            seen.add(key)
            new_rows.append(row)
        stad_payloads.extend(stadium_payloads_from_doc(doc))

    if new_rows:
        jsonl_util.append_jsonl(history, new_rows, json_kwargs={"default": str})

    stadium_saved = 0
    if stad_payloads:
        try:
            import stadium_tracker
            stadium_saved = stadium_tracker.ingest_payloads(stad_payloads, my_viewer_id=1)
        except Exception as e:
            print(f"  ! stadium ingest failed: {e}")

    return {
        "ok": True,
        "files": files_ok,
        "rows": len(new_rows),
        "stadium": stadium_saved,
        "not_horseact": not_horseact,
        "parse_errors": parse_errors,
    }


if __name__ == "__main__":
    import sys

    args = sys.argv[1:]
    if not args:
        sys.exit("usage: python horseact_import.py <file-or-dir> [more ...]")
    files: list[Path] = []
    for a in args:
        p = Path(a)
        if p.is_dir():
            files.extend(sorted(p.glob("*.json")))
        elif p.exists():
            files.append(p)
    print(import_paths(files))
