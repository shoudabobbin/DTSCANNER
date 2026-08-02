"""Write the morning watchlist as CSV and a self-contained HTML page.

The HTML is built for one job: a five-minute review before the open, on a
phone or a monitor, with no server and no dependencies. Green is long, red is
short, and the page says out loud how old the data it is showing you is.

Rows are embedded as JSON and rendered client-side so sorting, filtering and
search cost nothing and the file stays small.

`write_outputs` writes the dated archive copy into `output.dir` and, if
`output.publish_dir` is set, a copy at `<publish_dir>/index.html` for GitHub
Pages to serve.
"""
from __future__ import annotations

import html
import json
import shutil
from datetime import datetime

import numpy as np
import pandas as pd

from .config import Cfg, resolve

# (key, label, short label for compact table)
FIELDS = [
    ("rank", "Rank"), ("close", "Close"), ("adr_pct", "ADR%"),
    ("dist_to_trigger_pct", "To Trig%"), ("entry", "Entry"), ("stop", "Stop"),
    ("target_conservative", "T1"), ("target_aggressive", "T2"),
    ("risk_pct", "Risk%"), ("ext20_adr", "Ext (ADR)"),
    ("d_vs_20ma", "vs 20MA"), ("d_vs_200ma", "vs 200MA"),
    ("height_pct", "Height%"), ("length", "Bars"), ("score", "Score"),
]

CSV_DROP = ["_detail"]


def shortlist(df: pd.DataFrame, cfg: Cfg) -> pd.DataFrame:
    """Trim the full detection set down to the morning list."""
    o = cfg.output
    if df.empty:
        return df
    d = df.copy()
    if o.get("one_per_ticker", True):
        d = d.sort_values("rank", ascending=False).drop_duplicates("ticker")
    per_side = int(o.get("max_per_side", 999))
    d = (d.sort_values("rank", ascending=False)
           .groupby("side", group_keys=False, observed=True)
           .head(per_side))
    return d.sort_values("rank", ascending=False).head(
        int(o.get("max_rows", 25))).reset_index(drop=True)


# ------------------------------------------------------------------ helpers

def _clean(v):
    """JSON-safe scalar."""
    if v is None:
        return None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        f = float(v)
        return None if not np.isfinite(f) else round(f, 4)
    if isinstance(v, (np.bool_, bool)):
        return bool(v)
    if isinstance(v, pd.Timestamp):
        return str(v.date())
    if pd.isna(v) if np.isscalar(v) else False:
        return None
    return v


def _row_payload(r: pd.Series) -> dict:
    keep = ["ticker", "side", "pattern", "rank", "align", "tf", "close",
            "trigger", "entry", "stop", "target_conservative",
            "target_aggressive", "measured_move", "risk_pct",
            "dist_to_trigger_pct", "adr_pct", "ext20_adr", "atr_pct", "score",
            "structure", "volume", "readiness", "accum_ratio", "volume_ratio",
            "height_pct", "touches", "length", "d_vs_20ma", "d_vs_200ma",
            "w_trend", "h_trend", "dollar_volume", "date"]
    out = {k: _clean(r.get(k)) for k in keep}
    detail = r.get("_detail")
    out["detail"] = json.loads(json.dumps(detail, default=str)) if isinstance(
        detail, dict) else {}

    # H/D/W as an explicit 3-element list. Never derive this by splitting the
    # `tf` string on "/" — an unavailable timeframe reports "n/a", which used to
    # split into two fields and shift every badge one slot.
    tfs = (out["detail"].get("timeframes") or {})
    out["tfs"] = [str(tfs.get(k, {}).get("trend", "na")).replace("/", "")
                  for k in ("H", "D", "W")]
    return out


# ------------------------------------------------------------------- writing

def write_outputs(df: pd.DataFrame, regime: dict, cfg: Cfg,
                  data_note: dict | None = None) -> dict:
    out_dir = resolve(cfg, cfg.output["dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d")
    written = {}

    top = shortlist(df, cfg)

    if cfg.output.get("write_csv", True):
        p = out_dir / f"watchlist_{stamp}.csv"
        top.drop(columns=[c for c in CSV_DROP if c in top.columns]).to_csv(
            p, index=False)
        written["csv"] = p

    if cfg.output.get("write_html", True):
        page = _render(top, regime, stamp, cfg, data_note or {})
        p = out_dir / f"watchlist_{stamp}.html"
        p.write_text(page, encoding="utf-8")
        written["html"] = p

        pub = cfg.output.get("publish_dir")
        if pub:
            pub_dir = resolve(cfg, pub)
            pub_dir.mkdir(parents=True, exist_ok=True)
            (pub_dir / "index.html").write_text(page, encoding="utf-8")
            (pub_dir / ".nojekyll").write_text("")
            if "csv" in written:
                shutil.copyfile(written["csv"], pub_dir / "watchlist.csv")
            written["published"] = pub_dir / "index.html"

    return written


# -------------------------------------------------------------------- render

def _render(df: pd.DataFrame, regime: dict, stamp: str, cfg: Cfg,
            note: dict) -> str:
    rows = [_row_payload(r) for _, r in df.iterrows()] if not df.empty else []
    longs = sum(1 for r in rows if r["side"] == "long")
    shorts = sum(1 for r in rows if r["side"] == "short")

    bar_date = str(note.get("bar_date") or (rows[0]["date"] if rows else stamp))
    stale_n = int(note.get("stale_tickers", 0))
    universe_n = int(note.get("universe", 0))
    raw_n = int(note.get("raw_detections", 0))
    dropped_n = int(note.get("dropped", 0))

    payload = json.dumps({
        "rows": rows,
        "meta": {
            "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "barDate": bar_date,
            "regime": f'{regime.get("direction", "?")} · {regime.get("confidence", "?")}',
            "regimeScore": regime.get("score"),
            "longs": longs, "shorts": shorts,
            "universe": universe_n, "raw": raw_n,
            "staleTickers": stale_n, "dropped": dropped_n,
        },
    }, default=str)

    return _TEMPLATE.replace("__PAYLOAD__", payload).replace(
        "__TITLE__", html.escape(f"Watchlist {stamp}"))


_TEMPLATE = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark light">
<title>__TITLE__</title>
<style>
:root{
  --bg:#0d1117; --panel:#161b22; --panel2:#1c2230; --line:#2a3140;
  --txt:#e6edf3; --dim:#8b98a9; --faint:#5b6675;
  --long:#2ea043; --longbg:rgba(46,160,67,.13); --longln:rgba(46,160,67,.55);
  --short:#e5534b; --shortbg:rgba(229,83,75,.13); --shortln:rgba(229,83,75,.55);
  --warn:#d29922; --warnbg:rgba(210,153,34,.12);
  --accent:#58a6ff;
}
@media (prefers-color-scheme: light){
 :root{--bg:#f6f8fa;--panel:#fff;--panel2:#f0f3f6;--line:#d8dee4;--txt:#1f2328;
       --dim:#59636e;--faint:#8c959f;--long:#1a7f37;--short:#cf222e;--accent:#0969da;
       --longbg:rgba(26,127,55,.09);--shortbg:rgba(207,34,46,.09);
       --longln:rgba(26,127,55,.5);--shortln:rgba(207,34,46,.5);
       --warnbg:rgba(154,103,0,.1);--warn:#9a6700;}
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--txt);
  font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  -webkit-font-smoothing:antialiased}
.wrap{max-width:1500px;margin:0 auto;padding:18px 16px 60px}
header{display:flex;flex-wrap:wrap;align-items:baseline;gap:10px 14px;margin-bottom:12px}
h1{font-size:20px;margin:0;letter-spacing:-.2px;font-weight:650}
.sub{color:var(--dim);font-size:13px}
.pills{display:flex;flex-wrap:wrap;gap:6px;margin:2px 0 12px}
.pill{font-size:12px;padding:3px 10px;border-radius:20px;background:var(--panel);
  border:1px solid var(--line);color:var(--dim);white-space:nowrap}
.pill b{color:var(--txt);font-weight:600}
.pill.l b{color:var(--long)} .pill.s b{color:var(--short)}

.banner{display:flex;gap:10px;align-items:flex-start;background:var(--warnbg);
  border:1px solid rgba(210,153,34,.35);border-left:3px solid var(--warn);
  border-radius:8px;padding:10px 13px;margin:0 0 14px;font-size:12.5px;color:var(--txt)}
.banner .ic{color:var(--warn);font-weight:700;flex:none}
.banner span.k{color:var(--dim)}

.bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:14px}
.seg{display:inline-flex;background:var(--panel);border:1px solid var(--line);
  border-radius:8px;overflow:hidden}
.seg button{background:none;border:0;color:var(--dim);padding:6px 13px;font-size:12.5px;
  cursor:pointer;font-family:inherit;font-weight:550;border-right:1px solid var(--line)}
.seg button:last-child{border-right:0}
.seg button.on{background:var(--panel2);color:var(--txt)}
.seg button.on.l{color:var(--long)} .seg button.on.s{color:var(--short)}
input[type=search],select{background:var(--panel);border:1px solid var(--line);
  color:var(--txt);border-radius:8px;padding:6px 11px;font:inherit;font-size:12.5px;outline:0}
input[type=search]{width:150px}
input[type=search]:focus,select:focus{border-color:var(--accent)}
.spacer{flex:1}
.count{color:var(--faint);font-size:12px}

/* ---------------- cards ---------------- */
#cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(310px,1fr));gap:12px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;
  border-left:4px solid var(--line);overflow:hidden}
.card.long{border-left-color:var(--long)}
.card.short{border-left-color:var(--short)}
.chead{display:flex;align-items:center;gap:9px;padding:11px 13px 9px}
.tick{font-size:19px;font-weight:700;letter-spacing:-.3px}
.badge{font-size:10.5px;font-weight:700;letter-spacing:.07em;padding:2.5px 8px;
  border-radius:5px;text-transform:uppercase}
.badge.long{background:var(--longbg);color:var(--long)}
.badge.short{background:var(--shortbg);color:var(--short)}
.rk{margin-left:auto;text-align:right;line-height:1.1}
.rk b{font-size:17px;font-weight:650}
.rk i{display:block;font-style:normal;font-size:9.5px;color:var(--faint);
  letter-spacing:.09em;text-transform:uppercase}
.setup{padding:0 13px 9px;color:var(--dim);font-size:12px;display:flex;
  align-items:center;gap:8px;flex-wrap:wrap}
.tfs{display:inline-flex;gap:3px}
.tf{width:23px;text-align:center;border-radius:4px;font-size:9.5px;font-weight:700;
  padding:2px 0;background:var(--panel2);color:var(--faint);letter-spacing:.03em}
.tf.ok{background:var(--longbg);color:var(--long)}
.tf.bad{background:var(--shortbg);color:var(--short)}

/* level ladder */
.ladder{margin:2px 13px 11px;height:30px;position:relative}
.track{position:absolute;top:13px;left:0;right:0;height:3px;border-radius:2px;
  background:var(--panel2)}
.zone{position:absolute;top:13px;height:3px;border-radius:2px}
.zone.risk{background:var(--shortln)} .zone.rew{background:var(--longln)}
.mk{position:absolute;top:6px;width:2px;height:17px;border-radius:1px;background:var(--faint)}
.mk.entry{background:var(--txt);height:21px;top:4px;width:2.5px}
.mk.px{background:var(--accent);height:21px;top:4px;width:2.5px}
.mklbl{position:absolute;top:0;font-size:9px;color:var(--faint);transform:translateX(-50%);
  white-space:nowrap}
.mklbl.px{color:var(--accent)}

.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:var(--line);
  border-top:1px solid var(--line)}
.cell{background:var(--panel);padding:7px 10px 8px}
.cell k{display:block;font-size:9.5px;color:var(--faint);text-transform:uppercase;
  letter-spacing:.07em;font-weight:600;margin-bottom:1px}
.cell v{font-size:13px;font-variant-numeric:tabular-nums;font-weight:550}
v.pos{color:var(--long)} v.neg{color:var(--short)} v.mute{color:var(--dim)}
.more{width:100%;background:var(--panel2);border:0;border-top:1px solid var(--line);
  color:var(--faint);font:inherit;font-size:11px;padding:6px;cursor:pointer;
  letter-spacing:.05em}
.more:hover{color:var(--txt)}
pre.det{margin:0;padding:11px 13px;background:var(--panel2);font-size:10.5px;
  line-height:1.45;color:var(--dim);white-space:pre-wrap;word-break:break-word;
  max-height:340px;overflow:auto;border-top:1px solid var(--line)}
[hidden]{display:none!important}

/* ---------------- compact table ---------------- */
#tbl{width:100%;border-collapse:collapse;background:var(--panel);
  border:1px solid var(--line);border-radius:10px;overflow:hidden;font-size:12.5px}
#tbl th{background:var(--panel2);color:var(--faint);font-size:10px;text-transform:uppercase;
  letter-spacing:.06em;padding:8px 9px;text-align:right;white-space:nowrap;
  cursor:pointer;user-select:none;border-bottom:1px solid var(--line)}
#tbl th:first-child,#tbl td:first-child,#tbl th:nth-child(2),#tbl td:nth-child(2){text-align:left}
#tbl th:hover{color:var(--txt)}
#tbl td{padding:7px 9px;text-align:right;border-bottom:1px solid var(--line);
  white-space:nowrap;font-variant-numeric:tabular-nums}
#tbl tr:last-child td{border-bottom:0}
#tbl tbody tr{border-left:3px solid transparent}
#tbl tbody tr.long{border-left-color:var(--long)}
#tbl tbody tr.short{border-left-color:var(--short)}
#tbl tbody tr:hover{background:var(--panel2)}
#tbl td.t{font-weight:700}

.empty{color:var(--faint);text-align:center;padding:50px 20px;font-style:italic}
footer{margin-top:26px;padding-top:16px;border-top:1px solid var(--line);
  color:var(--faint);font-size:11.5px;line-height:1.6;max-width:900px}
footer b{color:var(--dim)}
@media(max-width:640px){
 .wrap{padding:14px 11px 50px} h1{font-size:17px}
 #cards{grid-template-columns:1fr}
 input[type=search]{width:110px}
}
</style></head>
<body><div class="wrap">

<header>
  <h1>Morning Watchlist</h1>
  <div class="sub" id="sub"></div>
</header>

<div class="pills" id="pills"></div>
<div class="banner" id="stale"></div>

<div class="bar">
  <div class="seg" id="sideseg">
    <button data-side="all" class="on">All</button>
    <button data-side="long" class="l">Long</button>
    <button data-side="short" class="s">Short</button>
  </div>
  <div class="seg" id="viewseg">
    <button data-view="cards" class="on">Cards</button>
    <button data-view="table">Table</button>
  </div>
  <select id="sort">
    <option value="rank">Sort: Rank</option>
    <option value="abstrig">Sort: Closest to trigger</option>
    <option value="adr_pct">Sort: ADR% (most movement)</option>
    <option value="risk_pct">Sort: Risk% (tightest first)</option>
    <option value="score">Sort: Pattern score</option>
    <option value="ticker">Sort: Ticker A–Z</option>
  </select>
  <input type="search" id="q" placeholder="Filter…" autocomplete="off">
  <span class="spacer"></span>
  <span class="count" id="count"></span>
</div>

<div id="cards"></div>
<div id="tblwrap" hidden></div>
<div class="empty" id="empty" hidden>Nothing matches.</div>

<footer id="foot"></footer>
</div>

<script>
const DATA = __PAYLOAD__;
const R = DATA.rows, M = DATA.meta;
let side = "all", view = "cards", sortKey = "rank", q = "";

const n = (v, d = 2) => (v === null || v === undefined || Number.isNaN(v)) ? "—" : Number(v).toFixed(d);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const sgn = v => (v === null || v === undefined) ? "mute" : (v > 0 ? "pos" : (v < 0 ? "neg" : "mute"));
const pretty = s => String(s || "").replace(/_/g, " ");

/* ---- header ---- */
document.getElementById("sub").textContent =
  "generated " + M.generated + " · from the " + M.barDate + " close";

document.getElementById("pills").innerHTML = [
  `<span class="pill l"><b>${M.longs}</b> long</span>`,
  `<span class="pill s"><b>${M.shorts}</b> short</span>`,
  `<span class="pill">market <b>${esc(M.regime)}</b></span>`,
  M.universe ? `<span class="pill"><b>${M.universe}</b> scanned</span>` : "",
  M.raw ? `<span class="pill"><b>${M.raw}</b> raw detections</span>` : "",
].join("");

/* ---- staleness: computed live, every time you open the page ---- */
(function () {
  const el = document.getElementById("stale");
  const close = new Date(M.barDate + "T16:00:00-05:00");   // ~US close
  const hrs = (Date.now() - close.getTime()) / 3.6e6;
  const d = Math.floor(hrs / 24), h = Math.round(hrs % 24);
  const age = d >= 1 ? `${d}d ${h}h` : `${Math.round(hrs)}h`;
  let extra = "";
  if (M.staleTickers) extra += ` <span class="k">·</span> ${M.staleTickers} symbol(s) had older data than the rest.`;
  if (M.dropped) extra += ` <span class="k">·</span> ${M.dropped} symbol(s) failed to download and were excluded.`;
  el.innerHTML = `<span class="ic">!</span><div><b>Built from the ${M.barDate} close — ${age} old.</b>
    Entry, stop and target levels have <b>not</b> been re-validated against today's pre-market.
    A gap through the entry means the level is already gone and the risk on the printed stop is no longer what it says.
    Check the live chart before acting on any row.${extra}</div>`;
})();

/* ---- ladder: stop | entry | price | T1 | T2 on a shared scale ---- */
function ladder(r) {
  const pts = [r.stop, r.entry, r.close, r.target_conservative, r.target_aggressive]
    .filter(v => v !== null && v !== undefined);
  if (pts.length < 4) return "";
  const lo = Math.min(...pts), hi = Math.max(...pts), span = hi - lo;
  if (!(span > 0)) return "";
  const pad = 7, x = v => pad + ((v - lo) / span) * (100 - 2 * pad);
  const a = x(r.stop), b = x(r.entry), c = x(r.close),
        t1 = x(r.target_conservative), t2 = x(r.target_aggressive);
  const rr = [Math.min(a, b), Math.max(a, b)], rw = [Math.min(b, t2), Math.max(b, t2)];
  return `<div class="ladder">
    <div class="track"></div>
    <div class="zone rew" style="left:${rw[0]}%;width:${rw[1] - rw[0]}%"></div>
    <div class="zone risk" style="left:${rr[0]}%;width:${rr[1] - rr[0]}%"></div>
    <div class="mk" style="left:${t1}%"></div>
    <div class="mk" style="left:${t2}%"></div>
    <div class="mk entry" style="left:${b}%"></div>
    <div class="mk px" style="left:${c}%"></div>
    <div class="mklbl" style="left:${a}%">stop</div>
    <div class="mklbl px" style="left:${c}%;top:19px">now</div>
    <div class="mklbl" style="left:${t2}%">T2</div>
  </div>`;
}

const TFNAME = ["hourly", "daily", "weekly"];
function tfBadges(r) {
  const want = r.side === "long" ? "up" : "down";
  const parts = Array.isArray(r.tfs) && r.tfs.length === 3
    ? r.tfs : ["na", "na", "na"];
  return '<span class="tfs">' + parts.map((p, i) => {
    const cls = p === want ? "ok" : (p === "up" || p === "down" ? "bad" : "");
    const lbl = p === "na" ? "–" : p.slice(0, 2);
    return `<span class="tf ${cls}" title="${TFNAME[i]}: ${esc(p)}">${esc(lbl)}</span>`;
  }).join("") + "</span>";
}

function card(r, i) {
  const dir = r.side === "long" ? 1 : -1;
  return `<div class="card ${r.side}">
    <div class="chead">
      <span class="tick">${esc(r.ticker)}</span>
      <span class="badge ${r.side}">${r.side}</span>
      <span class="rk"><b>${n(r.rank, 1)}</b><i>rank</i></span>
    </div>
    <div class="setup">${esc(pretty(r.pattern))} ${tfBadges(r)}</div>
    ${ladder(r)}
    <div class="grid">
      <div class="cell"><k>Close</k><v>${n(r.close)}</v></div>
      <div class="cell"><k>Entry</k><v>${n(r.entry)}</v></div>
      <div class="cell"><k>Stop</k><v class="neg">${n(r.stop)}</v></div>
      <div class="cell"><k>Risk</k><v>${n(r.risk_pct, 1)}%</v></div>
      <div class="cell"><k>T1</k><v class="pos">${n(r.target_conservative)}</v></div>
      <div class="cell"><k>T2</k><v class="pos">${n(r.target_aggressive)}</v></div>
      <div class="cell"><k>To trig</k><v class="${r.dist_to_trigger_pct < 0 ? "neg" : ""}">${n(r.dist_to_trigger_pct, 2)}%</v></div>
      <div class="cell"><k>ADR</k><v>${n(r.adr_pct, 1)}%</v></div>
      <div class="cell"><k>Ext 20MA</k><v class="mute">${n(r.ext20_adr, 1)}</v></div>
      <div class="cell"><k>vs 20MA</k><v class="${sgn(dir * r.d_vs_20ma)}">${n(r.d_vs_20ma, 1)}%</v></div>
      <div class="cell"><k>vs 200MA</k><v class="${sgn(dir * r.d_vs_200ma)}">${n(r.d_vs_200ma, 1)}%</v></div>
      <div class="cell"><k>Score</k><v class="mute">${n(r.score, 1)}</v></div>
    </div>
    <button class="more" onclick="tog(${i})">detail ▾</button>
    <pre class="det" id="d${i}" hidden>${esc(JSON.stringify(r.detail, null, 2))}</pre>
  </div>`;
}

function tog(i) {
  const e = document.getElementById("d" + i);
  e.hidden = !e.hidden;
  e.previousElementSibling.textContent = e.hidden ? "detail ▾" : "detail ▴";
}

const COLS = [["ticker", "Ticker"], ["pattern", "Setup"], ["rank", "Rank"],
["close", "Close"], ["dist_to_trigger_pct", "To Trig%"], ["entry", "Entry"],
["stop", "Stop"], ["target_conservative", "T1"], ["target_aggressive", "T2"],
["risk_pct", "Risk%"], ["adr_pct", "ADR%"], ["ext20_adr", "Ext"],
["d_vs_20ma", "vs20"], ["d_vs_200ma", "vs200"], ["score", "Score"]];

function table(rows) {
  const head = COLS.map(([k, l]) => `<th data-k="${k}">${l}</th>`).join("");
  const body = rows.map(r => "<tr class='" + r.side + "'>" + COLS.map(([k]) => {
    if (k === "ticker") return `<td class="t">${esc(r.ticker)}</td>`;
    if (k === "pattern") return `<td>${esc(pretty(r.pattern))}</td>`;
    const v = r[k];
    const dec = (k === "rank" || k === "adr_pct" || k === "risk_pct" || k === "score" || k === "ext20_adr") ? 1 : 2;
    return `<td>${n(v, dec)}</td>`;
  }).join("") + "</tr>").join("");
  return `<table id="tbl"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

function render() {
  let rows = R.filter(r => side === "all" || r.side === side);
  if (q) {
    const s = q.toLowerCase();
    rows = rows.filter(r => (r.ticker + " " + r.pattern).toLowerCase().includes(s));
  }
  const cmp = {
    rank: (a, b) => b.rank - a.rank,
    score: (a, b) => b.score - a.score,
    adr_pct: (a, b) => b.adr_pct - a.adr_pct,
    risk_pct: (a, b) => a.risk_pct - b.risk_pct,
    abstrig: (a, b) => Math.abs(a.dist_to_trigger_pct) - Math.abs(b.dist_to_trigger_pct),
    ticker: (a, b) => a.ticker.localeCompare(b.ticker),
  }[sortKey];
  rows = rows.slice().sort(cmp);

  document.getElementById("count").textContent =
    rows.length + " of " + R.length + " shown";
  document.getElementById("empty").hidden = rows.length > 0;

  const cw = document.getElementById("cards"), tw = document.getElementById("tblwrap");
  cw.hidden = view !== "cards"; tw.hidden = view === "cards";
  if (view === "cards") cw.innerHTML = rows.map((r, i) => card(r, R.indexOf(r))).join("");
  else tw.innerHTML = table(rows);
}

document.querySelectorAll("#sideseg button").forEach(b => b.onclick = () => {
  side = b.dataset.side;
  document.querySelectorAll("#sideseg button").forEach(x => x.classList.toggle("on", x === b));
  render();
});
document.querySelectorAll("#viewseg button").forEach(b => b.onclick = () => {
  view = b.dataset.view;
  document.querySelectorAll("#viewseg button").forEach(x => x.classList.toggle("on", x === b));
  render();
});
document.getElementById("sort").onchange = e => { sortKey = e.target.value; render(); };
document.getElementById("q").oninput = e => { q = e.target.value; render(); };

document.getElementById("foot").innerHTML = `
<b>Rank</b> is a sort key, not a probability — 40% timeframe alignment, 30% proximity to the
trigger, 15% structure, 15% average daily range. The project's own backtest found no predictive
power in the pattern score, and the rank key has not been validated against forward returns at all.
Treat every row as "worth opening the chart," nothing more.<br><br>
<b>H/D/W</b> = hourly / daily / weekly trend agreement with the trade direction. Green agrees,
red opposes, grey is mixed or unavailable. Note these use 20/200-period MAs on each timeframe,
which is ~3 days on hourly and ~4 years on weekly — they are not three views of the same horizon.<br><br>
<b>Entry / Stop / T1 / T2</b> are ATR-derived starting points computed from the prior close.
They are not recommendations, they do not account for earnings dates, gaps, borrow availability
on shorts, or slippage. <b>Ext (ADR)</b> is distance from the 20MA in average daily ranges —
near zero is coiled, ±3 is stretched.<br><br>
Informational only. Not financial advice.`;

render();
</script>
</body></html>
"""
