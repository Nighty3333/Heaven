# Heaven

[![Discord](https://img.shields.io/badge/Discord-Join%20the%20server-5865F2?logo=discord&logoColor=white)](https://discord.com/invite/SpCGcXMeFt)

Local dashboard for Uma Musume: **breeding optimizer**, **Team Trials analyzer**,
**skill planner** and **stadium tracker**. Runs as a small web
app on your own machine.

> **The dashboard is passive — it does not inject code, modify game memory, or
> send anything to the game server.** It only reads data: your account inventory
> (via the game's own API or a memory-dump import) and your Team Trials results.
> Everything runs locally at **http://127.0.0.1:1620**.

### Where the data comes from

| Data | How it's read |
|------|---------------|
| **Inventory / breeding** | Your account data via the game's own API (the same request your client makes on login), or a memory-dump import (UmaExtractor) |
| **Team Trials** | Either **(A)** imported from the in-game Heaven overlay's capture, or **(B)** captured from network traffic through a local HTTPS proxy (mitmproxy). Both just *read* — never modify packets |

> Method **A** (in-game overlay) is the simplest on the **Steam / Global** client
> and needs no proxy or certificate. Method **B** (mitmproxy) is the option for the
> **DMM** client.

---

## Requirements

- **Python 3.10+** (tested on 3.12 / 3.14)
- **Windows**
- Uma Musume (Steam/Global for method A, DMM for method B)

## Quick Start

```bash
git clone https://github.com/Nighty3333/Heaven.git
cd Heaven
python -m pip install -r requirements.txt
.\start.bat
```

Opens at **http://127.0.0.1:1620**.

> Use `python -m pip` (not bare `pip`) so every dependency installs into the
> **same** Python that runs the app. On a PC with more than one Python, a bare
> `pip` can install into a different environment, which later breaks Team Trials
> capture (method B).

---

## Features (tabs)

### Inventory
Your full character/factor inventory. Cards show the complete factor breakdown
(blue stats, pink aptitudes, green uniques, white skills/races) with star counts,
proc percentages, and your own contribution highlighted.
- Filter by name / note / tag / owner; source toggle (All / Yours / Friends).
- Sort by Affinity, G1 wins, white count, score, or newest.
- **Target picker** — pick any uma as breeding target to see exact individual
  affinity on every card.
- Inheritance-factor filters (uma.moe-style), progressive loading, quick "assign
  as Parent 1/2" actions.

### Breed Optimizer
Pick a target build (running style + distance) and your wanted skills; the
optimizer ranks the best parent pairs from your inventory.
- Uses an **expected-proc model**: the real probability of each spark proccing
  across all 6 tree entities (parents + 4 grandparents), each with its own
  individual affinity from the exact in-game formula (chara relation + winning
  saddle bonus + relation level).
- **Pair detail** — visual lineage tree with portraits + affinity badges, spark
  proc odds `P(>=1)` over a full run with per-source breakdown, and the combined
  inherited factors.
- A persistent **breeding tray** lets you assign parents while browsing.

### Team Trials
Every match you've played: your team vs the opponent, per-race results, skill
activations and win/loss verdicts.
- **Race Analysis** — compact per-uma rows: AVG score, CV% (consistency), BEST /
  WORST, ACT% (skill activation), a sparkline trend, and a verdict pill
  (GOAT / STRONG / SOLID / WEAK / BENCH). Click to expand a score heatmap, gap to
  top, stddev and full skill breakdown.
- **Re-train Comparison** — trained the same character more than once? Any uma with
  multiple versions gets a dropdown comparing them side by side (average, trimmed
  average, consistency, best/worst, win rate, skill activation and a per-distance
  breakdown) so you can see whether a re-train actually improved — older versions
  are kept for comparison instead of being hidden.
- The page **refreshes on its own** as new matches come in — no manual reload.

### Skill Planner
For a given (character, distance, running style), shows **how often each skill
actually fires** in your captured matches — so you pick skills that consistently
activate instead of ones that look good on paper but never trigger.

### Skill Lookup
Type any skill name and see **how often it actually activates** across all your
data — your Team Trials plus every race you've run (career, champions, room
matches). Filter the activation rate by **distance** and **running style**, with a
per-uma breakdown of who runs it and how reliably it fires.
- **Community pool** — the dashboard ships with a shared activation dataset and
  merges in any skill data you (or others) import, so the numbers get more
  reliable over time. Everything is **deduplicated** — the same race never counts
  twice.
- **Export / Import / Sync** — share your skill data or pull in someone else's;
  imports only ever *add* to your pool, never replace it.

### Track & Condition
Stadium conditions across your captured matches: top tracks, starting-gate
distribution, ground/surface/weather/season breakdowns and a full rounds table.
Also houses the **mitmproxy capture controls** (start/stop without a terminal).

---

## Setup

### 1) Import your account (Inventory / Breeding)

Open **http://127.0.0.1:1620** → the setup dialog offers two options:

**A — Memory dump (recommended, no Steam login)**
1. In Umamusume go to **Enhance → List** (Veteran List).
2. Run [UmaExtractor](https://github.com/xancia/UmaExtractor) → it writes `data.json`.
3. In Heaven's setup, click **Import data.json**.
   *(UmaExtractor reads only your own umas — friends' borrowable parents won't appear.)*

**B — Frida + Steam (advanced, includes friends' parents)**
1. Click **Open game & capture** — Heaven launches the game and captures the auth
   key via Frida.
2. Enter Steam username/password (and Steam Guard 2FA if enabled).
3. Heaven fetches your full inventory + friends' borrowable parents.
   Credentials are stored locally, encrypted via Windows DPAPI (same scheme Chrome
   uses) — they never leave your machine.

### 2) Team Trials data

**Method A — in-game overlay (Steam/Global):**
Run the in-game Heaven overlay, enable its **Team Trials** capture, and play a
match. Then in this dashboard click **Import in-game** (on the Team Trials tab) —
it reads the overlay's per-trial captures and merges them into your history. No
proxy, no certificate.

**Method B — mitmproxy (DMM):** a one-time setup, below.

<details>
<summary><b>Method B — mitmproxy setup (click to expand)</b></summary>

#### 2b.1 Generate the certificate
`mitmproxy` was installed in Quick Start via pip — **do not** install the
standalone build from mitmproxy.org (it ships its own frozen Python that can't see
`msgpack`/`pycryptodome`, which breaks capture). Run it once to create the CA cert,
then `Ctrl+C`:
```bash
mitmdump
```

#### 2b.2 Install the certificate
The cert is at `C:\Users\<YOU>\.mitmproxy\mitmproxy-ca-cert.cer`.

PowerShell (as Admin):
```powershell
Import-Certificate -FilePath "$env:USERPROFILE\.mitmproxy\mitmproxy-ca-cert.cer" -CertStoreLocation Cert:\LocalMachine\Root
```
> ⚠️ Mind the backslash before `.mitmproxy`. If you get *"certificate file could
> not be found"*, that missing `\` is almost always the cause.

Verify:
```powershell
Get-ChildItem Cert:\LocalMachine\Root | Where-Object { $_.Subject -like "*mitmproxy*" }
```

#### 2b.3 Capture
1. Open the **Track & Condition** tab → **Start Capture** (sets your Windows proxy
   automatically).
2. Play Team Trials in DMM.
3. **Stop Capture** (restores your Windows proxy) → see results on the Team Trials tab.

The proxy auto-detects your `udid` from request headers on first capture; if it
fails, save it to `data/udid.txt` (one line, 32 hex chars).

</details>

---

## Troubleshooting (mitmproxy / method B)

| Problem | Solution |
|---------|----------|
| `Import-Certificate : certificate file could not be found` | A `\` got dropped — use exactly `"$env:USERPROFILE\.mitmproxy\mitmproxy-ca-cert.cer"`. Or double-click the `.cer` and use the GUI |
| SSL / `SEC_ERROR` in the game | Cert not installed in **Local Machine → Trusted Root** (not Current User). Redo 2b.2 |
| `mitmdump exited immediately` / `ModuleNotFoundError: msgpack` | You installed the **standalone** mitmproxy (its embedded Python can't see the pip packages). Uninstall it (Settings → Apps → mitmproxy), then `python -m pip install -r requirements.txt`. Verify `(Get-Command mitmdump).Source` points at your Python's `Scripts\mitmdump.exe` |
| Capture running, no data | Traffic isn't going through the proxy. Check Windows Settings → Proxy = `127.0.0.1:8080` |
| Internet stuck after use | System proxy left on. Settings → Network → Proxy → turn **off**, or `Set-ItemProperty "HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings" ProxyEnable 0` |
| `udid` not auto-detected | Save it to `data/udid.txt` (32 hex chars) |

**Quick proxy test:** `mitmdump -s discover_addon.py --listen-port 8080 --set block_global=false`, then open the game — you should see `team_stadium/start`, `team_stadium/all_race_end` scrolling.

---

## Backups & importing data

Every import is **additive and deduplicated** — it only ever *adds* new data and
never overwrites or deletes what you already have, and it always takes a backup
first.

### Import & merge (Team Trials tab)
Pulls extra data into your dashboard. It auto-detects and accepts:
- a **Heaven export** bundle (from the *Export data* button),
- raw **horseACT / Team Trials** dumps,
- raw **UmaTTAnalyzer** data files (`team_trials_history.jsonl`,
  `stadium_observations.jsonl`).

You can select several files at once. Everything is deduplicated, so re-importing
the same data never doubles anything.

### Migrating from UmaTTAnalyzer
Moving over from UmaTTAnalyzer keeps **all** your history. Just take the files in
its `data/` folder (`team_trials_history.jsonl` and `stadium_observations.jsonl`)
and load them with **Import & merge** — your Team Trials, Track & Condition and
skill activation all come across in one step. Skill-only files can also go into
**Skill Lookup → Import data**, where they enrich your activation numbers without
touching your scores. Importing only *reads* those files; your original
UmaTTAnalyzer data is never modified.

### Backups
The **Backups** menu (top-left of the header) keeps dated restore points. A backup
is taken automatically before every import, and you can also make one any time
with **Backup now**. Pick any snapshot to roll back to it in one click — and since
your current data is snapshotted first, even a restore is undoable.

---

## Updating

```bash
cd Heaven
git pull
python -m pip install -r requirements.txt
.\start.bat
```

Your data (`data/` folder, notes, cached images) is local-only and untouched by
updates. Character portraits/icons are cached locally on first view (downloaded
from gametora on demand) — they are not redistributed in the repo.
