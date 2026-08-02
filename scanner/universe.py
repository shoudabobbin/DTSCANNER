"""Build the ticker universe.

Default: S&P 500 + S&P 400 (mid-cap) from Wikipedia, cached locally.
Add "sp600" to config -> universe.sources to expand toward ~1500 names, or
point "file" at your own newline-delimited list.

If Wikipedia is unreachable the module falls back to a bundled list of ~300
liquid large- and mid-caps, so a scan never dies on a network problem.
"""
from __future__ import annotations

import io
import json
import time
import urllib.request
from pathlib import Path

import pandas as pd

from .config import Cfg, resolve

WIKI = {
    "sp500": "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
    "sp400": "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies",
    "sp600": "https://en.wikipedia.org/wiki/List_of_S%26P_600_companies",
}

# Wikipedia returns 403 to clients that don't identify themselves, and
# pandas.read_html(url) sends no User-Agent at all. So fetch the HTML ourselves
# and hand the text to read_html instead of the URL.
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")


def _fetch_html(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers={
        "User-Agent": _UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def normalize(sym: str) -> str:
    """Yahoo uses '-' where the index lists use '.' (BRK.B -> BRK-B)."""
    return str(sym).strip().upper().replace(".", "-")


def _symbol_column(df: pd.DataFrame) -> str | None:
    for col in df.columns:
        name = str(col).lower()
        if "symbol" in name or "ticker" in name:
            return col
    return None


def _scrape(url: str) -> list[str]:
    tables = pd.read_html(io.StringIO(_fetch_html(url)))
    for tbl in tables:
        col = _symbol_column(tbl)
        if col is not None and len(tbl) > 50:
            return [normalize(s) for s in tbl[col].dropna().tolist()]
    raise ValueError(f"no constituent table found at {url}")


def build_universe(cfg: Cfg, force_refresh: bool = False) -> list[str]:
    ucfg = cfg.universe
    cache_dir = resolve(cfg, cfg.data["cache_dir"])
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / "universe.json"

    def _cached() -> list[str]:
        try:
            return json.loads(cache_file.read_text()).get("tickers", [])
        except Exception:
            return []

    max_age = ucfg.get("cache_days", 7) * 86400
    if cache_file.exists() and not force_refresh:
        if time.time() - cache_file.stat().st_mtime < max_age:
            try:
                blob = json.loads(cache_file.read_text())
            except Exception:
                blob = {}
            # never serve an empty cache — that just repeats yesterday's failure
            if blob.get("sources") == ucfg.get("sources") and blob.get("tickers"):
                return blob["tickers"]

    tickers: list[str] = []
    wiki_failed = False

    for src in ucfg.get("sources", []):
        if src in WIKI:
            try:
                got = _scrape(WIKI[src])
                print(f"  {src}: {len(got)} tickers")
                tickers += got
            except Exception as exc:
                wiki_failed = True
                print(f"  WARNING: could not fetch {src} ({exc})")
        elif src == "custom":
            tickers += [normalize(t) for t in ucfg.get("custom", [])]
        elif src == "file":
            fp = resolve(cfg, ucfg.get("file_path", "my_tickers.txt"))
            if fp.exists():
                tickers += [
                    normalize(line)
                    for line in fp.read_text().splitlines()
                    if line.strip() and not line.startswith("#")
                ]
            else:
                print(f"  WARNING: {fp} not found, skipping")

    if wiki_failed and not tickers:
        stale = _cached()
        if stale:
            print(f"  falling back to cached universe ({len(stale)} tickers)")
            tickers += stale
        else:
            print(f"  falling back to bundled list ({len(FALLBACK)} liquid names)")
            tickers += list(FALLBACK)

    # custom extras are always included, even if not listed as a source
    tickers += [normalize(t) for t in ucfg.get("custom", [])]

    seen, out = set(), []
    for t in tickers:
        if t and t not in seen and t.replace("-", "").isalnum():
            seen.add(t)
            out.append(t)

    if out:
        cache_file.write_text(json.dumps({"sources": ucfg.get("sources"),
                                          "tickers": out}))
    return out


# ---------------------------------------------------------------------------
# Bundled fallback: liquid US large- and mid-caps. Not an index — just names
# that reliably clear the $5M/day dollar-volume filter. Used only when the
# Wikipedia scrape fails and there is no cache to fall back on.
# ---------------------------------------------------------------------------
FALLBACK = [
    # mega / large cap tech
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "AVGO", "TSLA", "AMD",
    "ADBE", "CRM", "ORCL", "CSCO", "ACN", "INTU", "IBM", "QCOM", "TXN", "NOW",
    "AMAT", "MU", "LRCX", "KLAC", "ADI", "SNPS", "CDNS", "PANW", "ANET", "MRVL",
    "FTNT", "NXPI", "MCHP", "ON", "SWKS", "TER", "ENPH", "SMCI", "WDC", "STX",
    "HPQ", "DELL", "HPE", "NTAP", "JNPR", "ZS", "CRWD", "DDOG", "SNOW", "NET",
    "MDB", "TEAM", "WDAY", "HUBS", "OKTA", "TWLO", "DOCU", "ZM", "PLTR", "U",
    "RBLX", "SHOP", "SQ", "PYPL", "COIN", "HOOD", "SOFI", "AFRM", "TOST",
    # communication / media
    "NFLX", "DIS", "CMCSA", "T", "VZ", "TMUS", "WBD", "PARA", "EA", "TTWO",
    "SPOT", "PINS", "SNAP", "UBER", "LYFT", "DASH", "ABNB", "BKNG", "EXPE",
    # financials
    "BRK-B", "JPM", "BAC", "WFC", "C", "GS", "MS", "SCHW", "BLK", "SPGI",
    "AXP", "V", "MA", "USB", "PNC", "TFC", "COF", "BK", "STT", "FITB", "HBAN",
    "RF", "KEY", "CFG", "MTB", "ALLY", "DFS", "SYF", "AIG", "MET", "PRU",
    "TRV", "ALL", "PGR", "CB", "AFL", "HIG", "CINF", "WRB", "MMC", "AON",
    "ICE", "CME", "NDAQ", "MCO", "MSCI", "TROW", "BEN", "IVZ", "AMP", "RJF",
    # healthcare
    "UNH", "JNJ", "LLY", "ABBV", "MRK", "PFE", "TMO", "ABT", "DHR", "BMY",
    "AMGN", "GILD", "VRTX", "REGN", "BIIB", "MRNA", "ZTS", "SYK", "BSX", "MDT",
    "ISRG", "EW", "BDX", "BAX", "HOLX", "ALGN", "DXCM", "IDXX", "RMD", "ILMN",
    "CI", "CVS", "ELV", "HUM", "CNC", "MCK", "COR", "CAH", "HCA", "UHS", "DVA",
    "IQV", "A", "WAT", "MTD", "PKI", "TECH", "CRL", "LH", "DGX", "VTRS",
    # consumer
    "WMT", "COST", "TGT", "HD", "LOW", "TJX", "ROST", "BURL", "DG", "DLTR",
    "KR", "SYY", "PG", "KO", "PEP", "MDLZ", "MNST", "KDP", "STZ", "TAP",
    "CL", "KMB", "GIS", "K", "HSY", "SJM", "CAG", "CPB", "HRL", "TSN", "KHC",
    "MCD", "SBUX", "CMG", "YUM", "DRI", "DPZ", "QSR", "WEN", "TXRH",
    "NKE", "LULU", "DECK", "SKX", "CROX", "VFC", "PVH", "RL", "TPR", "CPRI",
    "F", "GM", "RIVN", "LCID", "APTV", "BWA", "LEA", "MGA", "HOG", "LKQ",
    "MAR", "HLT", "H", "WH", "RCL", "CCL", "NCLH", "LVS", "MGM", "WYNN", "CZR",
    "DKNG", "PENN", "EBAY", "ETSY", "W", "CHWY", "ORLY", "AZO", "AAP", "GPC",
    # industrials / energy / materials
    "CAT", "DE", "BA", "GE", "HON", "MMM", "RTX", "LMT", "NOC", "GD", "LHX",
    "TDG", "HWM", "TXT", "EMR", "ETN", "PH", "ROK", "DOV", "ITW", "CMI", "PCAR",
    "URI", "FAST", "GWW", "SWK", "IR", "XYL", "AME", "FTV", "PNR", "AOS",
    "UPS", "FDX", "UNP", "CSX", "NSC", "ODFL", "JBHT", "CHRW", "EXPD", "XPO",
    "DAL", "UAL", "AAL", "LUV", "ALK", "WM", "RSG", "WCN", "CLH",
    "XOM", "CVX", "COP", "EOG", "SLB", "HAL", "BKR", "OXY", "PSX", "VLO",
    "MPC", "HES", "DVN", "FANG", "APA", "MRO", "CTRA", "OKE", "WMB", "KMI",
    "LIN", "APD", "SHW", "ECL", "DD", "DOW", "LYB", "PPG", "NUE", "STLD",
    "FCX", "NEM", "MOS", "CF", "ALB", "VMC", "MLM", "IP", "PKG", "AMCR",
    # utilities / real estate / staples
    "NEE", "DUK", "SO", "D", "AEP", "EXC", "SRE", "XEL", "ED", "WEC", "ES",
    "PEG", "EIX", "PPL", "FE", "AEE", "CMS", "CNP", "NI", "LNT", "EVRG",
    "AMT", "PLD", "CCI", "EQIX", "DLR", "PSA", "SPG", "O", "WELL", "AVB",
    "EQR", "INVH", "MAA", "ESS", "UDR", "VTR", "ARE", "BXP", "KIM", "REG",
]
