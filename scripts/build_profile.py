"""Generate the animated SVG assets for the GitHub profile README.

Run locally:   GITHUB_TOKEN=... python scripts/build_profile.py
Run in CI:     .github/workflows/profile.yml (daily)

Every asset is written in a dark and a light variant (README switches with
<picture> + prefers-color-scheme). Fonts are subset per SVG and embedded as
base64, because GitHub serves SVGs as <img> which can't load external fonts.
Brand logos come from Simple Icons (CC0), bundled in scripts/icons.json.
Needs: fonttools.
"""

from __future__ import annotations

import base64
import io
import json
import math
import os
import re
import urllib.request
from datetime import datetime, timezone
from html import escape, unescape
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

USER = os.environ.get("PROFILE_USER", "Vishwas721")
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = ROOT / "assets"
ICONS = json.loads((HERE / "icons.json").read_text(encoding="utf-8"))

THEMES = {
    "dark": dict(
        bg="#07090f", panel="#0c111b", panel2="#111827", border="#1d283a", grid="#141d2c",
        text="#eef2f8", muted="#8b98ad", faint="#46546b",
        a1="#22d3ee", a2="#a78bfa", a3="#34d399", a4="#f472b6", warn="#fbbf24",
        chip="#121a28", chiptext="#c3cede", shade="#000000",
    ),
    "light": dict(
        bg="#ffffff", panel="#f7f9fc", panel2="#eef2f8", border="#d5dce7", grid="#e6ebf2",
        text="#0f172a", muted="#526077", faint="#a0acbd",
        a1="#0891b2", a2="#7c3aed", a3="#059669", a4="#db2777", warn="#b45309",
        chip="#ffffff", chiptext="#1e293b", shade="#64748b",
    ),
}

e = lambda s: escape(str(s), quote=True)  # noqa: E731


# --------------------------------------------------------------------------- #
# Fonts: instancing, measuring, subsetting + embedding
# --------------------------------------------------------------------------- #

FONT_FILES = {"D": "Unbounded.ttf", "S": "SpaceGrotesk.ttf", "M": "JetBrainsMono.ttf"}
FALLBACK = {
    "D": "'Segoe UI', Helvetica, Arial, sans-serif",
    "S": "'Segoe UI', Helvetica, Arial, sans-serif",
    "M": "Consolas, 'SFMono-Regular', Menlo, monospace",
}
_instances: dict[tuple[str, int], bytes] = {}
_metrics: dict[tuple[str, int], tuple] = {}
_used: set[tuple[str, int]] = set()


def _instance(fam: str, w: int) -> bytes:
    key = (fam, w)
    if key not in _instances:
        f = TTFont(HERE / "fonts" / FONT_FILES[fam])
        ax = next(a for a in f["fvar"].axes if a.axisTag == "wght")
        st = instancer.instantiateVariableFont(f, {"wght": min(max(w, ax.minValue), ax.maxValue)})
        buf = io.BytesIO()
        st.save(buf)
        _instances[key] = buf.getvalue()
        st2 = TTFont(io.BytesIO(_instances[key]))
        _metrics[key] = (st2.getBestCmap(), st2["hmtx"].metrics, st2["head"].unitsPerEm)
    return _instances[key]


def ff(fam: str, w: int) -> str:
    """CSS for a font face; records it so the face gets embedded."""
    _used.add((fam, w))
    return f"font-family:'{fam}',{FALLBACK[fam]};font-weight:{w}"


def measure(s: str, fam: str, w: int, size: float, ls: float = 0) -> float:
    _instance(fam, w)
    cmap, hm, upm = _metrics[(fam, w)]
    total = 0
    for ch in s:
        g = cmap.get(ord(ch))
        total += hm[g][0] if g else upm * 0.6
    return total * size / upm + ls * len(s)


def wrap(s: str, fam: str, w: int, size: float, max_w: float) -> list[str]:
    lines, cur = [], ""
    for word in s.split():
        nxt = f"{cur} {word}".strip()
        if measure(nxt, fam, w, size) > max_w and cur:
            lines.append(cur)
            cur = word
        else:
            cur = nxt
    return lines + ([cur] if cur else [])


def embed_fonts(svg: str) -> str:
    body = re.sub(r"<style>.*?</style>", "", svg, flags=re.S)
    chars = set(" ")
    for m in re.finditer(r">([^<>]+)<", body):
        chars |= set(unescape(m.group(1)))
    text = "".join(sorted(chars))
    css = []
    for fam, w in sorted(_used):
        font = TTFont(io.BytesIO(_instance(fam, w)))
        opts = subset.Options()
        opts.flavor = "woff"
        opts.hinting = False
        opts.name_IDs = []
        opts.layout_features = ["kern", "liga", "calt"]
        sub = subset.Subsetter(opts)
        sub.populate(text=text)
        sub.subset(font)
        buf = io.BytesIO()
        font.flavor = "woff"
        font.save(buf)
        b64 = base64.b64encode(buf.getvalue()).decode()
        css.append(f"@font-face{{font-family:'{fam}';font-weight:{w};src:url(data:font/woff;base64,{b64}) format('woff')}}")
    return svg.replace("<style>", "<style>" + "".join(css), 1)


def write(name: str, theme: str, svg: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    svg = embed_fonts(svg.strip())
    (OUT / f"{name}-{theme}.svg").write_text(svg + "\n", encoding="utf-8")
    _used.clear()


# --------------------------------------------------------------------------- #
# Icons
# --------------------------------------------------------------------------- #

def _lum(hexc: str) -> float:
    rgb = [int(hexc[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    rgb = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]


def contrast(a: str, b: str) -> float:
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def icon(t: dict, slug: str | None, x: float, y: float, size: float, color: str | None = None,
         mono: str = "") -> str:
    """Brand logo (24x24 Simple Icons path) or a monogram fallback."""
    if slug and slug in ICONS:
        ic = ICONS[slug]
        col = color or ic["hex"]
        if not color and contrast(col, t["chip"]) < 1.9:
            col = t["text"]
        s = size / 24
        return f'<path transform="translate({x:.1f},{y:.1f}) scale({s:.3f})" d="{ic["path"]}" fill="{col}"/>'
    col = color or t["a1"]
    fs = size * (0.5 if len(mono) <= 2 else 0.36)
    return (f'<rect x="{x:.1f}" y="{y:.1f}" width="{size}" height="{size}" rx="{size * .25:.1f}" fill="{col}" fill-opacity=".16" stroke="{col}" stroke-opacity=".5"/>'
            f'<text x="{x + size / 2:.1f}" y="{y + size / 2 + fs * .36:.1f}" text-anchor="middle" font-size="{fs:.1f}" fill="{col}" style="{ff("M", 700)}">{e(mono)}</text>')


TECH = {  # display name -> (simple-icons slug or None, monogram fallback)
    "Python": ("python", ""), "TypeScript": ("typescript", ""), "JavaScript": ("javascript", ""),
    "Rust": ("rust", ""), "Java": ("openjdk", ""), "SQL": (None, "SQL"),
    "React": ("react", ""), "Next.js": ("nextdotjs", ""), "Next.js 16": ("nextdotjs", ""),
    "React 19": ("react", ""), "Node.js": ("nodedotjs", ""), "FastAPI": ("fastapi", ""),
    "Tailwind": ("tailwindcss", ""), "Leaflet": ("leaflet", ""),
    "LangGraph": ("langgraph", ""), "LangChain": ("langchain", ""), "MCP": ("modelcontextprotocol", ""),
    "Ollama": ("ollama", ""), "Gemini": ("googlegemini", ""), "PyTorch": ("pytorch", ""),
    "YOLOv8": ("yolo", ""), "OpenCV": ("opencv", ""), "Pydantic": ("pydantic", ""),
    "PostgreSQL": ("postgresql", ""), "pgvector": (None, "pg"), "PostGIS": (None, "GIS"),
    "Neo4j": ("neo4j", ""), "Redis": ("redis", ""), "Redis/RQ": ("redis", ""), "Prisma": ("prisma", ""),
    "SQLAlchemy": ("sqlalchemy", ""), "H3": ("h3", ""), "Docker": ("docker", ""),
    "GitHub Actions": ("githubactions", ""), "Vercel": ("vercel", ""), "Git": ("git", ""),
    "Linux": ("linux", ""), "SearXNG": (None, "SX"), "Camoufox": (None, "CF"),
    "React Native": ("react", ""), "Playwright": (None, "PW"), "EasyOCR": (None, "OCR"),
}


def tech_icon(t: dict, name: str, x: float, y: float, size: float) -> str:
    slug, mono = TECH.get(name, (None, name[:2]))
    return icon(t, slug, x, y, size, mono=mono or name[:2])


# --------------------------------------------------------------------------- #
# GitHub data
# --------------------------------------------------------------------------- #

QUERY = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      totalCommitContributions totalPullRequestContributions totalIssueContributions
      contributionCalendar { totalContributions
        weeks { contributionDays { date contributionCount } } }
    }
    repositories(ownerAffiliations: OWNER, first: 100, isFork: false) {
      totalCount
      nodes { languages(first: 12, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name color } } } }
    }
    recent: repositories(ownerAffiliations: OWNER, first: 12, privacy: PUBLIC, isFork: false,
                         orderBy: {field: PUSHED_AT, direction: DESC}) {
      nodes { name defaultBranchRef { target { ... on Commit {
        history(first: 6) { nodes { oid messageHeadline committedDate
          author { user { login } } } } } } } }
    }
  }
}"""

IGNORED_LANGS = {"Batchfile", "PowerShell", "Dockerfile", "Mako", "PLpgSQL", "Shell", "GLSL"}


def fetch_stats() -> dict:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        raise SystemExit("GITHUB_TOKEN is required")
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": QUERY, "variables": {"login": USER}}).encode(),
        headers={"Authorization": f"bearer {token}", "User-Agent": "profile-builder"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        payload = json.load(r)
    if "errors" in payload:
        raise SystemExit(payload["errors"])
    u = payload["data"]["user"]
    cc = u["contributionsCollection"]
    cal = cc["contributionCalendar"]
    days = [d for w in cal["weeks"] for d in w["contributionDays"]]
    weeks = [sum(d["contributionCount"] for d in w["contributionDays"]) for w in cal["weeks"]]
    counts = [d["contributionCount"] for d in days]
    longest = run = 0
    for c in counts:
        run = run + 1 if c else 0
        longest = max(longest, run)
    current, i = 0, len(counts) - 1
    if i >= 0 and counts[i] == 0:  # today not over yet
        i -= 1
    while i >= 0 and counts[i]:
        current += 1
        i -= 1

    langs: dict[str, dict] = {}
    for repo in u["repositories"]["nodes"]:
        for edge in repo["languages"]["edges"]:
            n = edge["node"]["name"]
            if n in IGNORED_LANGS:
                continue
            langs.setdefault(n, {"size": 0, "color": edge["node"]["color"] or "#888888"})
            langs[n]["size"] += edge["size"]
    total = sum(v["size"] for v in langs.values()) or 1
    top = sorted(langs.items(), key=lambda kv: -kv[1]["size"])[:6]

    commits = []
    for repo in u["recent"]["nodes"]:
        if repo["name"].lower() == USER.lower() or not repo["defaultBranchRef"]:
            continue
        for c in repo["defaultBranchRef"]["target"]["history"]["nodes"]:
            login = ((c.get("author") or {}).get("user") or {}).get("login") or ""
            if login.lower() != USER.lower():
                continue
            commits.append(dict(repo=repo["name"], oid=c["oid"][:7], msg=c["messageHeadline"],
                                date=c["committedDate"]))
    commits.sort(key=lambda c: c["date"], reverse=True)
    seen: set[str] = set()
    per_repo = [c for c in commits if not (c["repo"] in seen or seen.add(c["repo"]))]
    commits = per_repo + [c for c in commits if c not in per_repo]

    return dict(
        total=cal["totalContributions"], commits=cc["totalCommitContributions"],
        prs=cc["totalPullRequestContributions"], issues=cc["totalIssueContributions"],
        repos=u["repositories"]["totalCount"], weeks=weeks,
        current=current, longest=longest, active_days=sum(1 for c in counts if c),
        best_day=max(counts) if counts else 0,
        langs=[(n, v["color"], v["size"] / total) for n, v in top],
        feed=commits[:7],
    )


# --------------------------------------------------------------------------- #
# Hero
# --------------------------------------------------------------------------- #

def hero(t: dict) -> str:
    W, H = 1200, 470
    # --- perspective floor -------------------------------------------------
    hz, vx = 352, 600
    floor = []
    for i in range(-14, 15):
        floor.append(f'<path d="M{vx + i * 34},{hz} L{vx + i * 210},{H}" />')
    for k in range(8):
        floor.append(
            f'<path d="M0,{hz} H{W}"><animateTransform attributeName="transform" type="translate" '
            f'values="0 0;0 {H - hz}" dur="4.8s" begin="-{k * 0.6:.1f}s" repeatCount="indefinite" '
            f'calcMode="spline" keyTimes="0;1" keySplines=".6 0 1 .6"/></path>'
        )
    # --- pipeline graph in a glass card -------------------------------------
    gx, gy, gw, gh = 716, 38, 446, 292
    nodes = {"ingest": (64, 104), "embed": (196, 76), "graph": (196, 186), "agent": (330, 126),
             "tools": (360, 226), "api": (214, 236), "ui": (74, 208)}
    edges = [("ingest", "embed"), ("ingest", "graph"), ("embed", "agent"), ("graph", "agent"),
             ("agent", "tools"), ("tools", "api"), ("agent", "api"), ("api", "ui"), ("ui", "ingest")]
    cols = [t["a1"], t["a2"], t["a3"], t["a1"], t["a2"], t["a4"], t["a1"], t["a3"], t["a2"]]
    es, ps = [], []
    for k, ((a, b), col) in enumerate(zip(edges, cols)):
        (x1, y1), (x2, y2) = nodes[a], nodes[b]
        es.append(f'<path id="hp{k}" d="M{x1},{y1} L{x2},{y2}" stroke="{t["border"]}" stroke-width="1.5"/>'
                  f'<path d="M{x1},{y1} L{x2},{y2}" stroke="{col}" stroke-width="1.5" class="flow" style="animation-delay:-{k * .37:.2f}s" opacity=".6"/>')
        dur = 2.2 + (k % 3) * .6
        ps.append(f'<circle r="3.4" fill="{col}" filter="url(#glow)"><animateMotion dur="{dur}s" begin="{k * .4:.1f}s" repeatCount="indefinite"><mpath href="#hp{k}"/></animateMotion>'
                  f'<animate attributeName="opacity" values="0;1;1;0" keyTimes="0;.1;.85;1" dur="{dur}s" begin="{k * .4:.1f}s" repeatCount="indefinite"/></circle>')
    ns = []
    for k, (name, (x, y)) in enumerate(nodes.items()):
        col = [t["a1"], t["a2"], t["a3"], t["a4"]][k % 4]
        ns.append(f'<g transform="translate({x},{y})"><circle r="22" fill="{col}" opacity=".12" class="pulse" style="animation-delay:{k * .4:.1f}s"/>'
                  f'<circle r="10" fill="{t["panel"]}" stroke="{col}" stroke-width="2"/><circle r="4" fill="{col}"/>'
                  f'<text y="36" text-anchor="middle" class="node">{e(name)}</text></g>')

    # --- left column --------------------------------------------------------
    name = "Vishwas K"
    nsize = 86
    while measure(name, "D", 800, nsize, -2) > 600:
        nsize -= 2
    lead = "Currently shipping"
    lead_w = measure(lead, "S", 400, 19) + 10
    rotating = ["agentic RAG that cites its sources", "a transit digital twin in Rust",
                "geospatial intelligence on PostGIS + H3", "local-first AI, zero cloud"]
    seg = 3.2
    cycle = seg * len(rotating)
    frac = 100 / len(rotating)
    rot = "".join(f'<text class="rot" style="animation-delay:{i * seg}s" x="{lead_w:.0f}" y="0">{e(s)}</text>'
                  for i, s in enumerate(rotating))
    chips_def = [("currently building Glacies", t["a3"], True), ("Bengaluru, IN", t["a1"], False),
                 ("B.Tech ISE · CGPA 9.16", t["a2"], False)]
    chips, cx = [], 0
    for label, col, live in chips_def:
        w = measure(label, "M", 500, 13) + 42
        dot = (f'<circle cx="17" cy="16" r="4" fill="{col}"/>'
               + (f'<circle cx="17" cy="16" r="4" fill="{col}" class="ring"/>' if live else ""))
        chips.append(f'<g transform="translate({cx:.0f},0)"><rect width="{w:.0f}" height="32" rx="16" fill="{t["chip"]}" fill-opacity=".85" stroke="{t["border"]}"/>{dot}'
                     f'<text x="30" y="21" class="chip">{e(label)}</text></g>')
        cx += w + 10

    return f"""
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-label="Vishwas K — AI and full-stack systems engineer">
<defs>
  <pattern id="dots" width="22" height="22" patternUnits="userSpaceOnUse"><circle cx="1.5" cy="1.5" r="1.1" fill="{t["grid"]}"/></pattern>
  <linearGradient id="nm" x1="0" x2="1"><stop offset="0" stop-color="{t["a1"]}"/><stop offset=".5" stop-color="{t["a2"]}"/><stop offset="1" stop-color="{t["a4"]}"/>
    <animateTransform attributeName="gradientTransform" type="translate" values="-.35 0;.35 0;-.35 0" dur="8s" repeatCount="indefinite"/></linearGradient>
  <linearGradient id="shine" x1="0" x2="1"><stop offset="0" stop-color="#fff" stop-opacity="0"/><stop offset=".5" stop-color="#fff" stop-opacity=".75"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>
  <linearGradient id="floorfade" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity="0"/><stop offset="1" stop-color="#fff" stop-opacity="1"/></linearGradient>
  <mask id="floormask"><rect y="{hz}" width="{W}" height="{H - hz}" fill="url(#floorfade)"/></mask>
  <filter id="blur" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="60"/></filter>
  <filter id="glow" x="-200%" y="-200%" width="500%" height="500%"><feGaussianBlur stdDeviation="2.5" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
  <clipPath id="frame"><rect width="{W}" height="{H}" rx="24"/></clipPath>
  <clipPath id="nameclip"><text x="-4" y="178" class="name">{name}</text></clipPath>
  <clipPath id="card"><rect x="{gx}" y="{gy}" width="{gw}" height="{gh}" rx="18"/></clipPath>
</defs>
<style>
  .name{{{ff("D", 800)};font-size:{nsize}px;letter-spacing:-2px}}
  .node{{{ff("M", 400)};font-size:11px;fill:{t["muted"]};letter-spacing:.5px}}
  .chip{{{ff("M", 500)};font-size:13px;fill:{t["chiptext"]}}}
  .prompt{{{ff("M", 400)};font-size:15px;fill:{t["muted"]}}}
  .bar{{{ff("M", 500)};font-size:12px;fill:{t["muted"]}}}
  .role{{{ff("S", 600)};font-size:26px;fill:{t["text"]}}}
  .lead{{{ff("S", 400)};font-size:19px;fill:{t["muted"]}}}
  .rot{{{ff("S", 600)};font-size:19px;fill:{t["a1"]};opacity:0;animation:rot {cycle}s infinite}}
  @keyframes rot{{0%{{opacity:0;transform:translateY(10px)}}{frac * .1:.1f}%{{opacity:1;transform:none}}{frac * .88:.1f}%{{opacity:1;transform:none}}{frac:.1f}%{{opacity:0;transform:translateY(-10px)}}100%{{opacity:0}}}}
  .flow{{stroke-dasharray:6 14;animation:flow 1.6s linear infinite}} @keyframes flow{{to{{stroke-dashoffset:-40}}}}
  .pulse{{transform-box:fill-box;transform-origin:center;animation:pulse 2.8s ease-in-out infinite}}
  @keyframes pulse{{0%,100%{{transform:scale(.7);opacity:.05}}50%{{transform:scale(1.25);opacity:.22}}}}
  .ring{{transform-box:fill-box;transform-origin:center;animation:ring 1.8s ease-out infinite}}
  @keyframes ring{{from{{transform:scale(1);opacity:.8}}to{{transform:scale(3.2);opacity:0}}}}
  .cursor{{animation:blink 1s steps(1) infinite}} @keyframes blink{{50%{{opacity:0}}}}
  .aur{{animation:aur 16s ease-in-out infinite alternate}} @keyframes aur{{to{{transform:translate(-120px,50px) scale(1.15)}}}}
  .rise{{opacity:0;animation:rise .9s cubic-bezier(.2,.7,.2,1) forwards}}
  @keyframes rise{{from{{opacity:0;transform:translateY(16px)}}to{{opacity:1;transform:none}}}}
  .sweep{{animation:sweep 5.5s ease-in-out infinite 1.4s}} @keyframes sweep{{0%{{transform:translateX(-260px)}}35%,100%{{transform:translateX(760px)}}}}
  .gl1,.gl2{{opacity:0;animation:gl 7s steps(1) infinite 2s}} .gl2{{animation-delay:2.06s}}
  @keyframes gl{{0%,88%,100%{{opacity:0;transform:none}}89%{{opacity:.75;transform:translate(-5px,2px)}}91%{{opacity:.6;transform:translate(4px,-2px)}}93%{{opacity:.8;transform:translate(-2px,0)}}94%{{opacity:0}}}}
</style>
<g clip-path="url(#frame)">
  <rect width="{W}" height="{H}" fill="{t["bg"]}"/>
  <rect width="{W}" height="{H}" fill="url(#dots)"/>
  <g filter="url(#blur)" opacity="{'.55' if t['bg'] != '#ffffff' else '.35'}">
    <ellipse class="aur" cx="900" cy="120" rx="260" ry="160" fill="{t["a2"]}"/>
    <ellipse class="aur" style="animation-delay:-6s" cx="320" cy="400" rx="300" ry="120" fill="{t["a1"]}"/>
    <ellipse class="aur" style="animation-delay:-11s" cx="640" cy="40" rx="180" ry="90" fill="{t["a4"]}" opacity=".6"/>
  </g>
  <g mask="url(#floormask)" stroke="{t["a2"]}" stroke-opacity=".5" stroke-width="1" fill="none">{"".join(floor)}</g>

  <g class="rise" style="animation-delay:.9s">
    <rect x="{gx}" y="{gy}" width="{gw}" height="{gh}" rx="18" fill="{t["panel"]}" fill-opacity=".72" stroke="{t["border"]}"/>
    <g clip-path="url(#card)">
      <rect x="{gx}" y="{gy}" width="{gw}" height="34" fill="{t["panel2"]}" fill-opacity=".8"/>
      <circle cx="{gx + 20}" cy="{gy + 17}" r="4" fill="{t["a3"]}"/><circle cx="{gx + 20}" cy="{gy + 17}" r="4" fill="{t["a3"]}" class="ring"/>
      <text x="{gx + 34}" y="{gy + 21}" class="bar">agent.pipeline</text>
      <text x="{gx + gw - 16}" y="{gy + 21}" class="bar" text-anchor="end">running · 7 nodes</text>
      <g transform="translate({gx},{gy + 14})" fill="none">{"".join(es)}{"".join(ps)}{"".join(ns)}</g>
    </g>
  </g>

  <g transform="translate(64,0)">
    <g class="rise" style="animation-delay:.1s"><text x="0" y="84" class="prompt"><tspan fill="{t["a3"]}">vishwas@dev</tspan><tspan fill="{t["faint"]}">:</tspan><tspan fill="{t["a1"]}">~</tspan><tspan fill="{t["faint"]}">$</tspan> whoami<tspan class="cursor" fill="{t["a1"]}"> ▋</tspan></text></g>
    <g class="rise" style="animation-delay:.3s">
      <text x="-4" y="178" class="name gl1" fill="{t["a1"]}">{name}</text>
      <text x="-4" y="178" class="name gl2" fill="{t["a4"]}">{name}</text>
      <text x="-4" y="178" class="name" fill="url(#nm)">{name}</text>
      <g clip-path="url(#nameclip)"><rect class="sweep" x="0" y="80" width="140" height="120" fill="url(#shine)" opacity="{'.55' if t['bg'] != '#ffffff' else '.8'}"/></g>
    </g>
    <g class="rise" style="animation-delay:.55s"><text x="0" y="226" class="role">AI &amp; Full-Stack Systems Engineer</text></g>
    <g class="rise" style="animation-delay:.8s"><g transform="translate(0,270)"><text x="0" y="0" class="lead">{lead}</text>{rot}</g></g>
    <g class="rise" style="animation-delay:1.05s"><g transform="translate(0,300)">{"".join(chips)}</g></g>
  </g>
  <rect x=".5" y=".5" width="{W - 1}" height="{H - 1}" rx="24" fill="none" stroke="{t["border"]}"/>
</g>
</svg>"""


# --------------------------------------------------------------------------- #
# Link buttons
# --------------------------------------------------------------------------- #

def _glyph(t: dict, kind: str, col: str) -> str:
    st = f'fill="none" stroke="{col}" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"'
    if kind == "portfolio":
        return (f'<g {st}><circle cx="12" cy="12" r="9.5"/><ellipse cx="12" cy="12" rx="4" ry="9.5"/>'
                f'<path d="M2.5 12h19M4 7h16M4 17h16"/></g>')
    if kind == "resume":
        return (f'<g {st}><path d="M6 2.5h8.5l4.5 4.5v14.5H6z"/><path d="M14.5 2.5V7H19"/>'
                f'<path d="M9 11.5h7M9 15h7M9 18.5h4"/></g>')
    if kind == "linkedin":
        return (f'<rect x="2" y="2" width="20" height="20" rx="4.5" fill="{col}"/>'
                f'<g fill="{t["panel"]}"><circle cx="7.4" cy="7.2" r="1.6"/><rect x="5.9" y="9.8" width="3" height="8.4" rx=".6"/>'
                f'<path d="M11 9.8h2.8v1.3c.5-.9 1.6-1.5 2.9-1.5 2.2 0 3.2 1.4 3.2 3.9v4.7h-3v-4.2c0-1.1-.4-1.8-1.4-1.8s-1.6.7-1.6 1.8v4.2H11z"/></g>')
    if kind == "email":
        return f'<path d="{ICONS["gmail"]["path"]}" fill="{col}"/>'
    return ""


BUTTONS = [
    ("portfolio", "Portfolio", "vshwk.vercel.app", "a1"),
    ("linkedin", "LinkedIn", "in/vishwas-k217", "a2"),
    ("resume", "Résumé", "view PDF", "a3"),
    ("email", "Email", "say hello", "a4"),
]


def button(t: dict, kind: str, label: str, sub: str, ak: str, idx: int) -> str:
    W, H = 300, 76
    col = t[ak]
    return f"""
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-label="{e(label)}: {e(sub)}">
<defs>
  <linearGradient id="bd" x1="0" x2="1" y1="0" y2="1"><stop offset="0" stop-color="{col}" stop-opacity=".9"/><stop offset=".45" stop-color="{t["border"]}"/><stop offset="1" stop-color="{t["border"]}"/></linearGradient>
  <linearGradient id="sh" x1="0" x2="1"><stop offset="0" stop-color="{col}" stop-opacity="0"/><stop offset=".5" stop-color="{col}" stop-opacity=".22"/><stop offset="1" stop-color="{col}" stop-opacity="0"/></linearGradient>
  <clipPath id="c"><rect x="1" y="1" width="{W - 2}" height="{H - 2}" rx="17"/></clipPath>
</defs>
<style>
  .l{{{ff("S", 700)};font-size:20px;fill:{t["text"]}}}
  .s{{{ff("M", 400)};font-size:12.5px;fill:{t["muted"]}}}
  .sw{{animation:sw 6s ease-in-out infinite {idx * .5}s}} @keyframes sw{{0%{{transform:translateX(-160px)}}40%,100%{{transform:translateX({W + 40}px)}}}}
  .ar{{animation:ar 2.4s ease-in-out infinite {idx * .3}s}} @keyframes ar{{50%{{transform:translate(3px,-3px)}}}}
</style>
<rect x="1" y="1" width="{W - 2}" height="{H - 2}" rx="17" fill="{t["panel"]}"/>
<g clip-path="url(#c)"><circle cx="40" cy="38" r="70" fill="{col}" opacity=".07"/><rect class="sw" x="0" y="0" width="140" height="{H}" fill="url(#sh)"/></g>
<rect x="1" y="1" width="{W - 2}" height="{H - 2}" rx="17" fill="none" stroke="url(#bd)" stroke-width="1.5"/>
<rect x="14" y="14" width="48" height="48" rx="13" fill="{col}" fill-opacity=".12" stroke="{col}" stroke-opacity=".35"/>
<g transform="translate(26,26)">{_glyph(t, kind, col)}</g>
<text x="78" y="35" class="l">{e(label)}</text>
<text x="78" y="56" class="s">{e(sub)}</text>
<g class="ar" transform="translate(0,0)"><path d="M{W - 40} 44 L{W - 26} 30 M{W - 37} 30 H{W - 26} V41" fill="none" stroke="{col}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></g>
</svg>"""


# --------------------------------------------------------------------------- #
# About (editor window)
# --------------------------------------------------------------------------- #

def about(t: dict) -> str:
    W = 1200
    K, S, P, C, N = t["a2"], t["a3"], t["text"], t["faint"], t["a1"]
    lines = [
        [(C, "// one engineer, many layers of the stack")],
        [(K, "const "), (N, "vishwas"), (P, " = {")],
        [(P, "  role:      "), (S, '"AI & Full-Stack Systems Engineer"'), (P, ",")],
        [(P, "  based:     "), (S, '"Bengaluru, India"'), (P, ",")],
        [(P, "  education: "), (S, '"B.Tech ISE @ REVA University — CGPA 9.16"'), (P, ",")],
        [(P, "  thinks_in: ["), (S, '"agents"'), (P, ", "), (S, '"graphs"'), (P, ", "), (S, '"geometry"'), (P, ", "), (S, '"latency budgets"'), (P, "],")],
        [(P, "  shipping:  ["), (S, '"Glacies"'), (P, ", "), (S, '"Preuve"'), (P, ", "), (S, '"Qnit"'), (P, ", "), (S, '"Panenka"'), (P, "],")],
        [(P, "  wins:      ["), (S, '"Top 15 — Code Cubicle 5.0 @ Microsoft"'), (P, "],")],
        [(P, "  principle: "), (S, '"if it can\'t cite its source, it doesn\'t ship"'), (P, ",")],
        [(P, "};")],
    ]
    lh, top = 31, 86
    H = top + lh * len(lines) + 46
    body, mini = [], []
    for i, segs in enumerate(lines):
        y = top + i * lh
        spans = "".join(f'<tspan fill="{c}">{e(s)}</tspan>' for c, s in segs)
        body.append(f'<g class="ln" style="animation-delay:{.25 + i * .14:.2f}s">'
                    f'<text x="38" y="{y}" class="num" text-anchor="end">{i + 1}</text>'
                    f'<text x="66" y="{y}" class="code" xml:space="preserve">{spans}</text></g>')
        mx = W - 92
        for c, s in segs:
            w = len(s) * 0.9
            if s.strip():
                mini.append(f'<rect x="{mx:.1f}" y="{62 + i * 6}" width="{w:.1f}" height="3" rx="1" fill="{c}" opacity=".55"/>')
            mx += len(s) * 0.9
    last_y = top + (len(lines) - 1) * lh
    cur_x = 66 + measure("};", "M", 400, 17) + 3
    return f"""
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-label="About: AI and full-stack systems engineer in Bengaluru, B.Tech ISE at REVA University, CGPA 9.16, Top 15 at Code Cubicle 5.0">
<style>
  .code{{{ff("M", 400)};font-size:17px}}
  .num{{{ff("M", 400)};font-size:14px;fill:{t["faint"]}}}
  .tab,.st{{{ff("M", 500)};font-size:12.5px;fill:{t["muted"]}}}
  .st{{fill:#fff;font-size:12px}}
  .ln{{opacity:0;animation:ln .5s ease-out forwards}}
  @keyframes ln{{from{{opacity:0;transform:translateX(-8px)}}to{{opacity:1;transform:none}}}}
  .cur{{animation:b 1s steps(1) infinite}} @keyframes b{{50%{{opacity:0}}}}
</style>
<rect x=".5" y=".5" width="{W - 1}" height="{H - 1}" rx="16" fill="{t["panel"]}" stroke="{t["border"]}"/>
<path d="M.5 46 H{W - .5}" stroke="{t["border"]}"/>
<circle cx="26" cy="23" r="6.5" fill="#ff5f57"/><circle cx="48" cy="23" r="6.5" fill="#febc2e"/><circle cx="70" cy="23" r="6.5" fill="#28c840"/>
<rect x="96" y="9" width="158" height="38" rx="8" fill="{t["bg"]}" stroke="{t["border"]}"/><rect x="96" y="40" width="158" height="8" fill="{t["bg"]}"/>
<rect x="96" y="9" width="158" height="2" fill="{t["a1"]}"/>
<g transform="translate(112,19) scale(.6)"><path d="{ICONS["typescript"]["path"]}" fill="#3178C6"/></g>
<text x="134" y="32" class="tab" fill="{t["text"]}">about.ts</text>
<g transform="translate(276,19) scale(.6)"><path d="{ICONS["rust"]["path"]}" fill="{t["muted"]}"/></g>
<text x="298" y="32" class="tab">raptor.rs</text>
<g transform="translate(400,19) scale(.6)"><path d="{ICONS["python"]["path"]}" fill="{t["muted"]}"/></g>
<text x="422" y="32" class="tab">agent.py</text>
<path d="M{W - 104} 54 V{H - 34}" stroke="{t["border"]}"/>
{"".join(mini)}
<rect x="{W - 100}" y="58" width="92" height="66" rx="3" fill="{t["a1"]}" opacity=".06"/>
<g transform="translate(14,0)">{"".join(body)}
<rect class="ln cur" style="animation-delay:{.25 + len(lines) * .14:.2f}s" x="{cur_x:.0f}" y="{last_y - 15}" width="9" height="20" fill="{t["a1"]}"/></g>
<path d="M.5 {H - 28} H{W - .5} V{H - 16} a15.5 15.5 0 0 1 -15.5 15.5 H16 a15.5 15.5 0 0 1 -15.5 -15.5z" fill="{t["a2"]}"/>
<text x="20" y="{H - 10}" class="st">⎇ main   ✓ 0 problems   ⚡ strict</text>
<text x="{W - 20}" y="{H - 10}" class="st" text-anchor="end">Ln {len(lines)}, Col 3   UTF-8   TypeScript</text>
</svg>"""


# --------------------------------------------------------------------------- #
# Stats
# --------------------------------------------------------------------------- #

def stats(t: dict, s: dict) -> str:
    W, H = 1200, 340
    tiles = [
        (f'{s["total"]:,}', "contributions", "last 12 months", t["a1"]),
        (f'{s["commits"]:,}', "commits", f'{s["active_days"]} active days', t["a2"]),
        (f'{s["prs"]:,}', "pull requests", f'{s["issues"]} issues opened', t["a3"]),
        (f'{s["current"]}d', "current streak", f'longest {s["longest"]} days', t["a4"]),
    ]
    tw = (W - 48 - 48) / 4
    tl = []
    for i, (val, label, sub, col) in enumerate(tiles):
        x = 24 + i * (tw + 16)
        tl.append(f'<g class="up" style="animation-delay:{.1 + i * .12:.2f}s"><g transform="translate({x:.1f},24)">'
                  f'<rect width="{tw:.1f}" height="110" rx="14" fill="{t["panel2"]}" stroke="{t["border"]}"/>'
                  f'<rect x="20" y="0" width="36" height="3" rx="1.5" fill="{col}"/>'
                  f'<circle cx="{tw - 26:.1f}" cy="26" r="5" fill="{col}" opacity=".9"/><circle cx="{tw - 26:.1f}" cy="26" r="5" fill="{col}" class="ring" style="animation-delay:{i * .5}s"/>'
                  f'<text x="20" y="58" class="val" fill="{col}">{e(val)}</text>'
                  f'<text x="20" y="82" class="lbl">{e(label)}</text>'
                  f'<text x="20" y="99" class="sub">{e(sub)}</text></g></g>')

    weeks = s["weeks"][-52:] or [0]
    gx, gy, gw, gh = 24, 172, 740, 128
    mx = max(weeks) or 1
    step = gw / max(len(weeks) - 1, 1)
    pts = [(gx + i * step, gy + gh - (v / mx) * (gh - 10)) for i, v in enumerate(weeks)]
    d = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    area = d + f" L{gx + gw:.1f},{gy + gh} L{gx},{gy + gh} Z"
    bars = "".join(
        f'<rect x="{x - 3:.1f}" y="{y:.1f}" width="6" height="{gy + gh - y:.1f}" rx="2" fill="{t["a2"]}" opacity=".13"/>'
        for x, y in pts)
    pk = max(range(len(weeks)), key=lambda i: weeks[i])
    px, py = pts[pk]
    grid = "".join(f'<path d="M{gx} {gy + gh * f:.1f} H{gx + gw}" stroke="{t["grid"]}" stroke-dasharray="3 5"/>' for f in (0, .5, 1))

    lx, ly, lw = 800, 184, 376
    bar, legend, acc = [], [], 0.0
    tf = sum(f for _, _, f in s["langs"]) or 1
    for i, (name, color, frac) in enumerate(s["langs"]):
        w = lw * frac / tf
        bar.append(f'<rect x="{lx + acc:.1f}" y="{ly}" width="{max(w - 2, 1):.1f}" height="12" fill="{color}"/>')
        acc += w
        cx_, ry = lx + (i % 2) * 196, ly + 46 + (i // 2) * 30
        slug = TECH.get(name, (None, ""))[0]
        ic = (icon(t, slug, cx_, ry - 14, 17, color=color) if slug else f'<circle cx="{cx_ + 8}" cy="{ry - 5}" r="6" fill="{color}"/>')
        legend.append(f'<g class="up" style="animation-delay:{.6 + i * .08:.2f}s">{ic}'
                      f'<text x="{cx_ + 26}" y="{ry}" class="lang">{e(name)}</text>'
                      f'<text x="{cx_ + 180}" y="{ry}" class="pct" text-anchor="end">{frac * 100:.1f}%</text></g>')
    updated = datetime.now(timezone.utc).strftime("%d %b %Y")
    return f"""
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-label="GitHub activity: {s["total"]} contributions, {s["commits"]} commits, {s["prs"]} pull requests in the last year">
<defs>
  <linearGradient id="ar" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="{t["a1"]}" stop-opacity=".35"/><stop offset="1" stop-color="{t["a1"]}" stop-opacity="0"/></linearGradient>
  <linearGradient id="lg" x1="0" x2="1"><stop offset="0" stop-color="{t["a2"]}"/><stop offset="1" stop-color="{t["a1"]}"/></linearGradient>
  <clipPath id="bar"><rect x="{lx}" y="{ly}" width="{lw}" height="12" rx="6"/></clipPath>
</defs>
<style>
  .val{{{ff("D", 700)};font-size:32px;letter-spacing:-1px}}
  .lbl{{{ff("S", 600)};font-size:16px;fill:{t["text"]}}}
  .sub,.cap,.pct{{{ff("M", 400)};font-size:12px;fill:{t["muted"]}}}
  .lang{{{ff("S", 500)};font-size:15px;fill:{t["text"]}}}
  .h{{{ff("M", 700)};font-size:12.5px;fill:{t["muted"]};letter-spacing:1.6px}}
  .up{{opacity:0;animation:up .7s cubic-bezier(.2,.7,.2,1) forwards}}
  @keyframes up{{from{{opacity:0;transform:translateY(10px)}}to{{opacity:1;transform:none}}}}
  .draw{{stroke-dasharray:3000;stroke-dashoffset:3000;animation:draw 2.6s .4s ease-out forwards}} @keyframes draw{{to{{stroke-dashoffset:0}}}}
  .fill{{opacity:0;animation:fi 1s 1.8s forwards}} @keyframes fi{{to{{opacity:1}}}}
  .grow{{transform-origin:{lx}px 0;transform:scaleX(0);animation:grow 1.4s .5s cubic-bezier(.2,.7,.2,1) forwards}} @keyframes grow{{to{{transform:scaleX(1)}}}}
  .ring{{transform-box:fill-box;transform-origin:center;animation:ring 2.2s ease-out infinite}}
  @keyframes ring{{from{{transform:scale(1);opacity:.7}}to{{transform:scale(3);opacity:0}}}}
</style>
<rect x=".5" y=".5" width="{W - 1}" height="{H - 1}" rx="18" fill="{t["panel"]}" stroke="{t["border"]}"/>
{"".join(tl)}
<text x="{gx}" y="{gy - 14}" class="h">WEEKLY CONTRIBUTIONS</text>
<text x="{gx + gw}" y="{gy - 14}" class="cap" text-anchor="end">peak {weeks[pk]} / week · best day {s["best_day"]}</text>
{grid}<g class="fill">{bars}</g>
<path d="{area}" fill="url(#ar)" class="fill"/>
<path d="{d}" fill="none" stroke="url(#lg)" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round" class="draw"/>
<g class="fill"><circle cx="{px:.1f}" cy="{py:.1f}" r="4.5" fill="{t["a1"]}"/><circle cx="{px:.1f}" cy="{py:.1f}" r="4.5" fill="{t["a1"]}" class="ring"/></g>
<path d="M{lx - 18} 156 V{H - 24}" stroke="{t["border"]}"/>
<text x="{lx}" y="{gy - 14}" class="h">LANGUAGES</text>
<text x="{lx + lw}" y="{gy - 14}" class="cap" text-anchor="end">{s["repos"]} repos</text>
<g clip-path="url(#bar)"><rect x="{lx}" y="{ly}" width="{lw}" height="12" fill="{t["grid"]}"/><g class="grow">{"".join(bar)}</g></g>
{"".join(legend)}
<text x="{W - 24}" y="{H - 14}" class="cap" text-anchor="end" opacity=".7">auto-updated {updated}</text>
</svg>"""


# --------------------------------------------------------------------------- #
# Commit feed (terminal)
# --------------------------------------------------------------------------- #

def feed(t: dict, s: dict) -> str:
    W = 1200
    rows = s["feed"]
    top, lh = 104, 34
    H = top + lh * (len(rows) + 1) + 18
    repo_w = max([measure(r["repo"], "M", 700, 15) for r in rows] + [80]) + 22
    out = []
    for i, r in enumerate(rows):
        y = top + i * lh
        d = datetime.fromisoformat(r["date"].replace("Z", "+00:00")).strftime("%b %d")
        msg_max = W - 110 - 160 - repo_w - 120
        msg = r["msg"]
        while measure(msg, "M", 400, 15) > msg_max and len(msg) > 4:
            msg = msg[:-2].rstrip() + "…" if not msg.endswith("…") else msg[:-2] + "…"
        col = [t["a1"], t["a2"], t["a3"], t["a4"]][sum(map(ord, r["repo"])) % 4]
        delay = .6 + i * .28
        out.append(
            f'<g class="row" style="animation-delay:{delay:.2f}s">'
            f'<text x="36" y="{y}" class="m"><tspan fill="{t["warn"]}">{e(r["oid"])}</tspan></text>'
            f'<rect x="124" y="{y - 17}" width="{repo_w:.0f}" height="24" rx="6" fill="{col}" fill-opacity=".12" stroke="{col}" stroke-opacity=".35"/>'
            f'<text x="{124 + 11}" y="{y}" class="m b" fill="{col}">{e(r["repo"])}</text>'
            f'<text x="{124 + repo_w + 16:.0f}" y="{y}" class="m" fill="{t["text"]}">{e(msg)}</text>'
            f'<text x="{W - 36}" y="{y}" class="m" text-anchor="end" fill="{t["muted"]}">{d}</text></g>')
    end_y = top + len(rows) * lh
    return f"""
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-label="Latest commits across public repositories">
<style>
  .m{{{ff("M", 400)};font-size:15px}} .b{{{ff("M", 700)}}}
  .t{{{ff("M", 500)};font-size:12.5px;fill:{t["muted"]}}}
  .row{{opacity:0;animation:row .35s ease-out forwards}}
  @keyframes row{{from{{opacity:0;transform:translateX(-10px)}}to{{opacity:1;transform:none}}}}
  .type{{animation:type 1.2s steps(48) forwards}} @keyframes type{{from{{width:0}}to{{width:640px}}}}
  .cur{{animation:b 1s steps(1) infinite}} @keyframes b{{50%{{opacity:0}}}}
</style>
<defs><clipPath id="tc"><rect class="type" x="36" y="40" width="0" height="40"/></clipPath></defs>
<rect x=".5" y=".5" width="{W - 1}" height="{H - 1}" rx="16" fill="{t["bg"] if t["bg"] != "#ffffff" else t["panel"]}" stroke="{t["border"]}"/>
<path d="M.5 40 H{W - .5}" stroke="{t["border"]}"/>
<circle cx="24" cy="20" r="6" fill="#ff5f57"/><circle cx="44" cy="20" r="6" fill="#febc2e"/><circle cx="64" cy="20" r="6" fill="#28c840"/>
<text x="{W / 2}" y="25" class="t" text-anchor="middle">zsh — ~/vishwas721 — latest commits</text>
<g clip-path="url(#tc)"><text x="36" y="68" class="m"><tspan fill="{t["a3"]}">➜</tspan><tspan fill="{t["a1"]}">  ~ </tspan><tspan fill="{t["text"]}">git log --all-repos --author=vishwas --oneline</tspan></text></g>
{"".join(out)}
<g class="row" style="animation-delay:{.6 + len(rows) * .28:.2f}s"><text x="36" y="{end_y}" class="m"><tspan fill="{t["a3"]}">➜</tspan><tspan fill="{t["a1"]}">  ~ </tspan></text>
<rect class="cur" x="{36 + measure("➜  ~ ", "M", 400, 15):.0f}" y="{end_y - 15}" width="9" height="19" fill="{t["a1"]}"/></g>
</svg>"""


# --------------------------------------------------------------------------- #
# Project cover art (580 x 150)
# --------------------------------------------------------------------------- #

CW, CH = 580, 150


def art_glacies(t, p):
    g = "".join(f'<path d="M{x} 0 V{CH}" stroke="{t["grid"]}"/>' for x in range(0, CW, 24))
    g += "".join(f'<path d="M0 {y} H{CW}" stroke="{t["grid"]}"/>' for y in range(6, CH, 24))
    lines = [
        (t["a1"], [(20, 112), (120, 112), (180, 62), (330, 62), (400, 32), (560, 32)]),
        (t["a2"], [(30, 24), (140, 50), (220, 100), (380, 100), (460, 128), (570, 128)]),
        (t["a4"], [(90, 146), (160, 96), (260, 96), (330, 62), (470, 72), (560, 88)]),
    ]
    out = [g]
    for k, (col, pts) in enumerate(lines):
        d = "M" + " L".join(f"{x},{y}" for x, y in pts)
        out.append(f'<path id="{p}l{k}" d="{d}" fill="none" stroke="{col}" stroke-width="5" stroke-linecap="round" stroke-linejoin="round" opacity=".85"/>')
        for x, y in pts[1:-1]:
            out.append(f'<circle cx="{x}" cy="{y}" r="4.5" fill="{t["panel"]}" stroke="{col}" stroke-width="2.2"/>')
        out.append(f'<rect x="-9" y="-4" width="18" height="8" rx="4" fill="#fff" stroke="{col}" stroke-width="2">'
                   f'<animateMotion dur="{6 + k * 1.3}s" begin="-{k * 2}s" repeatCount="indefinite" rotate="auto"><mpath href="#{p}l{k}"/></animateMotion></rect>')
    out.append(f'<circle cx="330" cy="62" r="8" fill="{t["panel"]}" stroke="{t["text"]}" stroke-width="2.5"/>')
    return "".join(out)


def art_summaid(t, p):
    a, b = t["a3"], t["a1"]
    doc = [f'<rect x="60" y="16" width="140" height="122" rx="8" fill="{t["panel"]}" stroke="{t["border"]}"/>',
           f'<rect x="74" y="28" width="60" height="6" rx="3" fill="{t["faint"]}"/>']
    widths = [110, 96, 104, 88, 108, 70, 100]
    for i, w in enumerate(widths):
        y = 44 + i * 12
        if i == 3:
            doc.append(f'<rect x="70" y="{y - 3}" width="{w + 8}" height="10" rx="3" fill="{a}" opacity=".25"><animate attributeName="opacity" values=".15;.5;.15" dur="2.4s" repeatCount="indefinite"/></rect>')
        doc.append(f'<rect x="74" y="{y}" width="{w}" height="4" rx="2" fill="{a if i == 3 else t["faint"]}" opacity="{1 if i == 3 else .6}"/>')
    summ = [f'<rect x="380" y="26" width="150" height="100" rx="10" fill="{t["panel"]}" stroke="{b}" stroke-opacity=".5"/>',
            f'<rect x="394" y="40" width="70" height="7" rx="3.5" fill="{b}"/>']
    for i, w in enumerate([118, 100, 110, 64]):
        summ.append(f'<rect x="394" y="{60 + i * 14}" width="{w}" height="4.5" rx="2" fill="{t["faint"]}" opacity=".7"/>')
    summ.append(f'<rect x="462" y="98" width="24" height="15" rx="4" fill="{a}"/><text x="474" y="109.5" text-anchor="middle" font-size="10" fill="{t["panel"]}" style="{ff("M", 700)}">p.3</text>')
    link = f'M190,{44 + 36 + 2} C280,{44 + 36} 380,140 462,106'
    return ("".join(doc) + "".join(summ)
            + f'<path id="{p}c" d="{link}" fill="none" stroke="{a}" stroke-width="1.8" stroke-dasharray="5 6" class="dash"/>'
            + f'<circle r="4" fill="{a}"><animateMotion dur="2.4s" repeatCount="indefinite" keyPoints="1;0" keyTimes="0;1" calcMode="linear"><mpath href="#{p}c"/></animateMotion></circle>'
            + f'<text x="290" y="54" text-anchor="middle" font-size="11" fill="{t["muted"]}" style="{ff("M", 500)}">glass-box citation</text>')


def art_privex(t, p):
    a = t["a2"]
    out = [f'<rect x="130" y="12" width="320" height="128" rx="10" fill="{t["bg"]}" stroke="{t["border"]}"/>',
           f'<rect x="130" y="12" width="320" height="22" rx="10" fill="{t["panel2"]}"/><rect x="130" y="26" width="320" height="8" fill="{t["panel2"]}"/>',
           f'<circle cx="146" cy="23" r="3.5" fill="#ff5f57"/><text x="160" y="27" font-size="10" fill="{t["muted"]}" style="{ff("M", 500)}">meet.live · screen share</text>',
           f'<circle cx="430" cy="23" r="4" fill="#ff5f57"><animate attributeName="opacity" values="1;.2;1" dur="1.2s" repeatCount="indefinite"/></circle>',
           f'<rect x="148" y="46" width="120" height="80" rx="6" fill="{t["panel2"]}"/><circle cx="208" cy="76" r="14" fill="{t["faint"]}"/><rect x="184" y="96" width="48" height="22" rx="11" fill="{t["faint"]}"/>',
           f'<rect x="282" y="46" width="152" height="80" rx="6" fill="{t["panel2"]}"/>',
           f'<text x="292" y="66" font-size="10.5" fill="{t["muted"]}" style="{ff("M", 400)}">.env</text>',
           f'<text x="292" y="86" font-size="11" fill="{t["text"]}" style="{ff("M", 500)}">API_KEY=sk-9f2c41</text>',
           f'<text x="292" y="106" font-size="11" fill="{t["text"]}" style="{ff("M", 500)}">DB_PASS=hunter2</text>',
           f'<rect x="290" y="75" height="15" rx="3" fill="{t["text"]}" width="0"><animate attributeName="width" values="0;0;124;124;0" keyTimes="0;.3;.4;.9;1" dur="4s" repeatCount="indefinite"/></rect>',
           f'<rect x="290" y="95" height="15" rx="3" fill="{t["text"]}" width="0"><animate attributeName="width" values="0;0;112;112;0" keyTimes="0;.45;.55;.9;1" dur="4s" repeatCount="indefinite"/></rect>',
           f'<g><rect width="140" height="30" rx="4" fill="none" stroke="{a}" stroke-width="2" stroke-dasharray="6 4"/>'
           f'<rect y="-15" width="88" height="14" rx="3" fill="{a}"/><text x="5" y="-4.5" font-size="9.5" fill="#fff" style="{ff("M", 700)}">secret · 0.97</text>'
           f'<animateTransform attributeName="transform" type="translate" values="160,60;286,74;286,94;160,60" keyTimes="0;.35;.55;1" dur="4s" repeatCount="indefinite"/></g>',
           f'<rect x="130" y="34" width="320" height="2" fill="{a}" opacity=".7"><animate attributeName="y" values="36;136;36" dur="3s" repeatCount="indefinite"/></rect>',
           ]
    for i, (x, y) in enumerate([(40, 40), (70, 110), (520, 50), (500, 116)]):
        out.append(f'<circle cx="{x}" cy="{y}" r="3" fill="{a}" opacity=".5"/><path d="M{x},{y} L{130 if x < 300 else 450},{y}" stroke="{a}" stroke-opacity=".25" stroke-dasharray="2 4"/>')
    return "".join(out)


def art_qnit(t, p):
    a, b = t["a4"], t["warn"]
    out = []
    for k in range(7):
        r0 = 18 + k * 15
        pts = []
        for j in range(48):
            th = j / 48 * 2 * math.pi
            r = r0 * (1 + .12 * math.sin(3 * th + k) + .06 * math.cos(5 * th - k))
            pts.append(f"{430 + r * math.cos(th) * 1.5:.1f},{78 + r * math.sin(th) * .8:.1f}")
        out.append(f'<path d="M{" L".join(pts)} Z" fill="none" stroke="{t["a1"]}" stroke-opacity="{.55 - k * .06:.2f}" stroke-width="1.2"/>')
    out.append(f'<path d="M20,140 Q290,-40 560,140" id="{p}sun" fill="none" stroke="{b}" stroke-opacity=".45" stroke-dasharray="3 5"/>')
    out.append(f'<circle r="9" fill="{b}" opacity=".25"><animateMotion dur="9s" repeatCount="indefinite"><mpath href="#{p}sun"/></animateMotion></circle>'
               f'<circle r="5" fill="{b}"><animateMotion dur="9s" repeatCount="indefinite"><mpath href="#{p}sun"/></animateMotion></circle>')
    poly = "M120,58 L230,46 L262,104 L178,128 L110,104 Z"
    out.append(f'<path d="{poly}" fill="{a}" fill-opacity=".14" stroke="{a}" stroke-width="2" stroke-dasharray="7 5" class="dash"/>')
    for x, y in [(120, 58), (230, 46), (262, 104), (178, 128), (110, 104)]:
        out.append(f'<rect x="{x - 3.5}" y="{y - 3.5}" width="7" height="7" fill="{t["panel"]}" stroke="{a}" stroke-width="1.8"/>')
    out.append(f'<text x="186" y="92" text-anchor="middle" font-size="10.5" fill="{a}" style="{ff("M", 700)}">SITE 01</text>')
    for i, (lab, x) in enumerate([("flood: low", 300), ("wind: SW", 300), ("zone: R2", 300)]):
        out.append(f'<text x="{40}" y="{24 + i * 14}" font-size="10" fill="{t["muted"]}" style="{ff("M", 400)}">{lab} [{i + 1}]</text>')
    out.append(f'<text x="560" y="24" text-anchor="end" font-size="12" fill="{t["muted"]}" style="{ff("M", 700)}">N ↑</text>')
    return "".join(out)


def art_preuve(t, p):
    labels = ["opinion", "reply", "call", "commit", "pay"]
    hs = [104, 80, 58, 40, 26]
    cols = [t["faint"], t["faint"], t["a1"], t["a1"], t["a3"]]
    out = [f'<path d="M60 132 H520" stroke="{t["border"]}"/>']
    for i, (lab, h, col) in enumerate(zip(labels, hs, cols)):
        x = 80 + i * 90
        out.append(f'<rect x="{x}" width="56" rx="6" fill="{col}" fill-opacity="{.35 if i < 2 else .8}" y="132" height="0">'
                   f'<animate attributeName="height" values="0;{h};{h};0" keyTimes="0;.3;.85;1" dur="5s" begin="{i * .15}s" repeatCount="indefinite" calcMode="spline" keySplines=".2 .7 .2 1;0 0 1 1;.6 0 1 1"/>'
                   f'<animate attributeName="y" values="132;{132 - h};{132 - h};132" keyTimes="0;.3;.85;1" dur="5s" begin="{i * .15}s" repeatCount="indefinite" calcMode="spline" keySplines=".2 .7 .2 1;0 0 1 1;.6 0 1 1"/></rect>'
                   f'<text x="{x + 28}" y="146" text-anchor="middle" font-size="10" fill="{t["muted"]}" style="{ff("M", 500)}">{lab}</text>')
    out.append(f'<g transform="translate(468,62)"><circle r="12" fill="{t["a3"]}"/><path d="M-5 0 l3.5 3.5 l6.5 -7" stroke="#fff" stroke-width="2.4" fill="none" stroke-linecap="round" stroke-linejoin="round"/>'
               f'<animate attributeName="opacity" values="0;0;1;1;0" keyTimes="0;.32;.4;.85;1" dur="5s" repeatCount="indefinite"/></g>')
    out.append(f'<text x="60" y="22" font-size="10.5" fill="{t["muted"]}" style="{ff("M", 500)}">signal strength ↓ · trust ↑</text>')
    return "".join(out)


def art_panenka(t, p):
    a = t["a3"]
    ln = f'fill="none" stroke="{a}" stroke-opacity=".55" stroke-width="1.6"'
    out = [f'<rect x="0" y="0" width="{CW}" height="{CH}" fill="{a}" opacity=".05"/>']
    for k in range(0, CW, 58):
        out.append(f'<rect x="{k}" y="0" width="29" height="{CH}" fill="{a}" opacity=".035"/>')
    out.append(f'<path d="M40 10 H560 V140 H40 Z M40 10 V140" {ln}/><path d="M40 10 V140" {ln}/>'
               f'<circle cx="40" cy="75" r="34" {ln}/><path d="M456 32 H560 M456 32 V118 H560" {ln}/>'
               f'<path d="M524 54 V96 H560 M524 54 H560" {ln}/><path d="M456 54 A28 28 0 0 0 456 96" {ln}/><circle cx="490" cy="75" r="2.5" fill="{a}"/>')
    out.append(f'<path d="M560 58 H572 V92 H560" fill="none" stroke="{t["text"]}" stroke-width="3"/>')
    out.append(f'<path d="M560 58 L572 58 L572 92 L560 92" fill="none" stroke="{t["text"]}" stroke-opacity=".2"/>')
    out.append(f'<g><rect x="-3" y="-14" width="6" height="28" rx="3" fill="{t["a4"]}"/><circle cy="-19" r="4" fill="{t["a4"]}"/>'
               f'<animateTransform attributeName="transform" type="translate" values="550,75;550,75;552,104;552,104;550,75" keyTimes="0;.25;.42;.9;1" dur="4s" repeatCount="indefinite"/></g>')
    path = f"M490,75 Q526,6 562,72"
    out.append(f'<path id="{p}b" d="{path}" fill="none" stroke="{t["text"]}" stroke-opacity=".35" stroke-dasharray="2 5"/>')
    out.append(f'<g><circle r="5.5" fill="#fff" stroke="{t["shade"]}" stroke-width="1"/>'
               f'<animateMotion dur="4s" repeatCount="indefinite" keyPoints="0;0;1;1" keyTimes="0;.3;.62;1" calcMode="linear"><mpath href="#{p}b"/></animateMotion></g>')
    out.append(f'<text x="60" y="28" font-size="10.5" fill="{t["muted"]}" style="{ff("M", 700)}">PANENKA · chipped, keeper dives</text>')
    out.append(f'<text x="150" y="96" font-size="34" fill="{a}" opacity=".18" style="{ff("D", 700)}">0.82 xG</text>')
    return "".join(out)


def art_klados(t, p):
    r = 13
    w, h = math.sqrt(3) * r, 1.5 * r
    out = []
    cx0, cy0 = 300, 75
    for row in range(-1, int(CH / h) + 2):
        for col in range(-1, int(CW / w) + 2):
            x = col * w + (w / 2 if row % 2 else 0)
            y = row * h
            pts = " ".join(f"{x + r * math.cos(math.radians(60 * k - 30)):.1f},{y + r * math.sin(math.radians(60 * k - 30)):.1f}" for k in range(6))
            dist = math.hypot(x - cx0, y - cy0)
            lead = (row * 7 + col * 3) % 23 == 0
            col_ = t["a4"] if lead else t["a2"]
            out.append(f'<polygon points="{pts}" fill="{col_}" fill-opacity="{.5 if lead else .04}" stroke="{t["border"]}" stroke-width="1">'
                       + ("" if lead else f'<animate attributeName="fill-opacity" values=".04;.5;.04;.04" keyTimes="0;.12;.35;1" dur="4s" begin="{dist / 160:.2f}s" repeatCount="indefinite"/>')
                       + '</polygon>')
    out.append(f'<circle cx="{cx0}" cy="{cy0}" r="5" fill="{t["a2"]}"/>')
    return "".join(out)


def art_nagarikone(t, p):
    a = t["a4"]
    out = [f'<path d="M0 100 C120 80 200 130 330 96 S520 40 {CW} 60" stroke="{t["a1"]}" stroke-opacity=".25" stroke-width="10" fill="none"/>']
    for d in ["M0 40 H580", "M0 128 H580", "M110 0 V150", "M260 0 V150", "M420 0 V150", "M40 0 L200 150", "M330 0 L520 150"]:
        out.append(f'<path d="{d}" stroke="{t["faint"]}" stroke-opacity=".35" stroke-width="3" fill="none"/>')
    pin = "M0,0 C-7,-9 -11,-14 -11,-21 A11,11 0 1 1 11,-21 C11,-14 7,-9 0,0Z"
    for i, (x, y, col) in enumerate([(160, 92, t["a1"]), (440, 70, t["a3"])]):
        out.append(f'<circle cx="{x}" cy="{y}" r="10" fill="none" stroke="{col}" stroke-width="1.5"><animate attributeName="r" values="6;38" dur="2.6s" begin="{i * .8}s" repeatCount="indefinite"/><animate attributeName="opacity" values=".9;0" dur="2.6s" begin="{i * .8}s" repeatCount="indefinite"/></circle>'
                   f'<path transform="translate({x},{y})" d="{pin}" fill="{col}"/><circle cx="{x}" cy="{y - 21}" r="4" fill="{t["panel"]}"/>')
    x, y = 300, 84
    out.append(f'<circle cx="{x}" cy="{y}" r="40" fill="{a}" fill-opacity=".08" stroke="{a}" stroke-dasharray="4 4"/>'
               f'<text x="{x + 46}" y="{y + 36}" font-size="10" fill="{a}" style="{ff("M", 700)}">50 m</text>'
               f'<path transform="translate({x},{y})" d="{pin}" fill="{a}"/><circle cx="{x}" cy="{y - 21}" r="4" fill="{t["panel"]}"/>'
               f'<g><path d="{pin}" fill="{a}" opacity=".85"/><circle cy="-21" r="4" fill="{t["panel"]}"/>'
               f'<animateTransform attributeName="transform" type="translate" values="{x + 24},{y - 60};{x + 24},{y + 8};{x},{y};{x},{y}" keyTimes="0;.3;.55;1" dur="3.4s" repeatCount="indefinite"/>'
               f'<animate attributeName="opacity" values="0;1;1;0;0" keyTimes="0;.1;.5;.6;1" dur="3.4s" repeatCount="indefinite"/></g>'
               f'<g opacity="0"><rect x="{x - 40}" y="{y - 64}" width="80" height="18" rx="9" fill="{a}"/><text x="{x}" y="{y - 51.5}" text-anchor="middle" font-size="10" fill="#fff" style="{ff("M", 700)}">merged ×2</text>'
               f'<animate attributeName="opacity" values="0;0;1;1;0" keyTimes="0;.55;.62;.92;1" dur="3.4s" repeatCount="indefinite"/></g>')
    return "".join(out)


PROJECTS = [
    dict(slug="glacies", name="Glacies", kind="Urban transit digital twin", status=("BUILDING", "a3"), accent="a1", art=art_glacies,
         blurb="Models a city's transit network from open data, generates synthetic demand and answers “what if we changed the network?” — starting with Bengaluru.",
         metric=("GTFS + OSM", "→ Rust RAPTOR → scenarios"), stack=["Rust", "Python", "TypeScript", "Docker"]),
    dict(slug="summaid", name="SummAID", kind="On-prem medical intelligence", status=("SHIPPED", "a1"), accent="a3", art=art_summaid,
         blurb="Hybrid RAG over encrypted patient records with a “Glass Box” citation system linking every claim back to its source page.",
         metric=("12 min → <50 s", "clinical review time"), stack=["Python", "FastAPI", "pgvector", "LangChain"]),
    dict(slug="privex", name="Privex", kind="Agentic visual firewall", status=("SHIPPED", "a1"), accent="a2", art=art_privex,
         blurb="Redacts credentials from live meetings with YOLOv8 + OCR, and remembers context through a vector + Neo4j graph memory orchestrated by LangGraph.",
         metric=("Vector + Graph", "multi-hop hybrid memory"), stack=["LangGraph", "YOLOv8", "Neo4j", "MCP"]),
    dict(slug="qnit", name="Qnit", kind="Cited site intelligence · India", status=("LIVE", "a3"), accent="a4", art=art_qnit,
         blurb="Draw a site, get flood, sun path, wind, zoning and infrastructure context — every number cited with source, version and date.",
         metric=("₹20k–50k", "of consultant work, automated"), stack=["Next.js 16", "React 19", "Python", "Leaflet"]),
    dict(slug="preuve", name="Preuve", kind="Evidence-driven idea validation", status=("BUILDING", "a3"), accent="a1", art=art_preuve,
         blurb="Validates startup ideas by finding people who actually have the problem and measuring behaviour and commitment, not opinions.",
         metric=("Hybrid LLM", "local Ollama + Gemini"), stack=["FastAPI", "Next.js", "Redis", "SearXNG"]),
    dict(slug="panenka", name="Panenka", kind="Local-first football analytics", status=("SHIPPED", "a1"), accent="a3", art=art_panenka,
         blurb="Private match and player analytics on local Postgres, with a Model Context Protocol server so AI agents can query the stats.",
         metric=("109 tests", "passing · strict TypeScript"), stack=["Next.js", "Prisma", "PostgreSQL", "MCP"]),
    dict(slug="klados", name="Klados", kind="Lead discovery engine", status=("LIVE", "a3"), accent="a2", art=art_klados,
         blurb="Sweeps cities cell by cell on an H3 grid, audits every business website in a stealth browser and turns the gaps into ready-to-send pitches.",
         metric=("H3 res-9", "grid scanning + site audits"), stack=["FastAPI", "Redis/RQ", "H3", "Ollama"]),
    dict(slug="nagarikone", name="NagarikOne", kind="Geospatial civic reporting", status=("PILOTED", "a1"), accent="a4", art=art_nagarikone,
         blurb="Citizens report civic issues; PostGIS auto-merges duplicates within a 50 m radius. Validated on a live pilot across Bengaluru.",
         metric=("50 m · <5 s", "geo-dedupe latency"), stack=["React Native", "PostGIS", "Node.js", "Vercel"]),
]


def card(t: dict, p: dict, idx: int) -> str:
    W, H = CW, 424
    acc = t[p["accent"]]
    st_label, st_col = p["status"][0], t[p["status"][1]]
    lines = wrap(p["blurb"], "S", 400, 15.5, W - 56)[:3]
    blurb = "".join(f'<text x="28" y="{258 + i * 23}" class="b">{e(l)}</text>' for i, l in enumerate(lines))
    chips, cx = [], 28
    for s in p["stack"]:
        w = measure(s, "M", 500, 12.5) + 44
        chips.append(f'<g transform="translate({cx:.0f},{H - 50})"><rect width="{w:.0f}" height="30" rx="8" fill="{t["chip"]}" stroke="{t["border"]}"/>'
                     f'{tech_icon(t, s, 9, 7, 16)}<text x="32" y="19.5" class="c">{e(s)}</text></g>')
        cx += w + 8
    sw = measure(st_label, "M", 700, 11, 1) + 32
    mw = measure(p["metric"][0], "D", 700, 21)
    return f"""
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-label="{e(p["name"])}: {e(p["kind"])}">
<defs>
  <radialGradient id="glo" cx="1" cy="1" r="1"><stop offset="0" stop-color="{acc}" stop-opacity=".16"/><stop offset=".7" stop-color="{acc}" stop-opacity="0"/></radialGradient>
  <linearGradient id="cv" x1="0" x2="0" y1="0" y2="1"><stop offset=".55" stop-color="{t["panel"]}" stop-opacity="0"/><stop offset="1" stop-color="{t["panel"]}" stop-opacity=".9"/></linearGradient>
  <linearGradient id="bd" x1="0" x2="1" y1="0" y2="1"><stop offset="0" stop-color="{acc}" stop-opacity=".7"/><stop offset=".4" stop-color="{t["border"]}"/></linearGradient>
  <clipPath id="cc"><rect width="{W}" height="{H}" rx="20"/></clipPath>
</defs>
<style>
  .t{{{ff("D", 700)};font-size:27px;fill:{t["text"]};letter-spacing:-.6px}}
  .k{{{ff("M", 500)};font-size:12px;fill:{acc};letter-spacing:1.4px}}
  .b{{{ff("S", 400)};font-size:15.5px;fill:{t["muted"]}}}
  .c{{{ff("M", 500)};font-size:12.5px;fill:{t["chiptext"]}}}
  .st{{{ff("M", 700)};font-size:11px;letter-spacing:1px;fill:{st_col}}}
  .mv{{{ff("D", 700)};font-size:21px;fill:{acc}}}
  .ml{{{ff("M", 400)};font-size:12.5px;fill:{t["muted"]}}}
  .dash{{animation:dash 1.4s linear infinite}} @keyframes dash{{to{{stroke-dashoffset:-22}}}}
  .dot{{animation:d 1.6s ease-in-out infinite}} @keyframes d{{50%{{opacity:.25}}}}
</style>
<g clip-path="url(#cc)">
  <rect width="{W}" height="{H}" fill="{t["panel"]}"/>
  <rect width="{W}" height="{H}" fill="url(#glo)"/>
  <rect width="{W}" height="{CH}" fill="{t["panel2"]}"/>
  <g>{p["art"](t, p["slug"])}</g>
  <rect width="{W}" height="{CH}" fill="url(#cv)"/>
  <path d="M0 {CH} H{W}" stroke="{t["border"]}"/>
</g>
<rect x=".75" y=".75" width="{W - 1.5}" height="{H - 1.5}" rx="20" fill="none" stroke="url(#bd)" stroke-width="1.5"/>
<g transform="translate({W - 18 - sw:.0f},16)"><rect width="{sw:.0f}" height="26" rx="13" fill="{t["panel"]}" fill-opacity=".9" stroke="{st_col}" stroke-opacity=".55"/>
<circle class="dot" cx="14" cy="13" r="3.8" fill="{st_col}"/><text x="24" y="17" class="st">{e(st_label)}</text></g>
<text x="28" y="186" class="k">{e(p["kind"].upper())}</text>
<text x="28" y="226" class="t">{e(p["name"])}</text>
{blurb}
<text x="28" y="{H - 74}" class="mv">{e(p["metric"][0])}</text>
<text x="{28 + mw + 12:.0f}" y="{H - 74}" class="ml">{e(p["metric"][1])}</text>
{"".join(chips)}
</svg>"""


# --------------------------------------------------------------------------- #
# Toolbox bento
# --------------------------------------------------------------------------- #

TOOLBOX = [
    ("AI · AGENTS · VISION", "a2", ["LangGraph", "LangChain", "MCP", "Ollama", "Gemini", "PyTorch", "YOLOv8", "OpenCV", "Pydantic"]),
    ("LANGUAGES", "a1", ["Python", "TypeScript", "Rust", "JavaScript", "Java", "SQL"]),
    ("WEB & APIs", "a3", ["React", "Next.js", "FastAPI", "Node.js", "Tailwind", "Leaflet"]),
    ("DATA & GEO", "a4", ["PostgreSQL", "pgvector", "PostGIS", "Neo4j", "Redis", "Prisma", "SQLAlchemy", "H3"]),
    ("INFRA", "a1", ["Docker", "GitHub Actions", "Vercel", "Git", "Linux"]),
]


def toolbox(t: dict) -> str:
    W, gap, pad = 1200, 16, 20
    tile_w, tile_h, tg = 156, 46, 10
    col3 = (W - 2 * gap) / 3
    layout = [(0, 0, col3 * 2 + gap), (1, col3 * 2 + 2 * gap, col3), (2, 0, col3), (3, col3 + gap, col3),
              (4, (col3 + gap) * 2, col3)]

    def rows_for(n, w):
        per = max(1, int((w - 2 * pad + tg) // (tile_w + tg)))
        return math.ceil(n / per), per

    r1 = max(rows_for(len(TOOLBOX[i][2]), w)[0] for i, _, w in layout[:2])
    r2 = max(rows_for(len(TOOLBOX[i][2]), w)[0] for i, _, w in layout[2:])
    h1, h2 = 58 + r1 * (tile_h + tg) + 10, 58 + r2 * (tile_h + tg) + 10
    H = h1 + gap + h2
    cards, n = [], 0
    for li, (i, x, w) in enumerate(layout):
        label, ak, items = TOOLBOX[i]
        col = t[ak]
        y = 0 if li < 2 else h1 + gap
        h = h1 if li < 2 else h2
        _, per = rows_for(len(items), w)
        tiles = []
        tw = (w - 2 * pad - (per - 1) * tg) / per
        for k, name in enumerate(items):
            tx = pad + (k % per) * (tw + tg)
            ty = 54 + (k // per) * (tile_h + tg)
            tiles.append(f'<g class="pop" style="animation-delay:{.1 + n * .035:.2f}s"><g transform="translate({tx:.1f},{ty})">'
                         f'<rect width="{tw:.1f}" height="{tile_h}" rx="11" fill="{t["chip"]}" stroke="{t["border"]}"/>'
                         f'{tech_icon(t, name, 13, 12, 22)}'
                         f'<text x="46" y="28.5" class="n">{e(name)}</text></g></g>')
            n += 1
        cards.append(
            f'<g transform="translate({x:.1f},{y})">'
            f'<rect width="{w:.1f}" height="{h}" rx="18" fill="{t["panel"]}" stroke="{t["border"]}"/>'
            f'<rect width="{w:.1f}" height="{h}" rx="18" fill="url(#cg{li})"/>'
            f'<circle cx="{pad + 4}" cy="30" r="4" fill="{col}"/>'
            f'<text x="{pad + 16}" y="35" class="h" fill="{col}">{e(label)}</text>'
            f'<text x="{w - pad:.1f}" y="35" class="cnt" text-anchor="end">{len(items):02d}</text>'
            f'{"".join(tiles)}</g>')
    grads = "".join(f'<radialGradient id="cg{li}" cx="1" cy="0" r="1"><stop offset="0" stop-color="{t[TOOLBOX[i][1]]}" stop-opacity=".12"/><stop offset=".6" stop-color="{t[TOOLBOX[i][1]]}" stop-opacity="0"/></radialGradient>'
                    for li, (i, _, _) in enumerate(layout))
    return f"""
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-label="Toolbox: {e(", ".join(x for _, _, it in TOOLBOX for x in it))}">
<defs>{grads}</defs>
<style>
  .h{{{ff("M", 700)};font-size:12.5px;letter-spacing:1.6px}}
  .cnt{{{ff("D", 700)};font-size:15px;fill:{t["faint"]}}}
  .n{{{ff("S", 500)};font-size:15px;fill:{t["chiptext"]}}}
  .pop{{opacity:0;animation:pop .5s cubic-bezier(.2,.7,.2,1) forwards}}
  @keyframes pop{{from{{opacity:0;transform:translateY(8px)}}to{{opacity:1;transform:none}}}}
</style>
{"".join(cards)}
</svg>"""


# --------------------------------------------------------------------------- #
# Section headers
# --------------------------------------------------------------------------- #

def header(t: dict, idx: str, title: str, sub: str) -> str:
    W, H = 1200, 78
    return f"""
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-label="{e(title)}">
<defs><linearGradient id="hl" x1="0" x2="1"><stop offset="0" stop-color="{t["a1"]}"/><stop offset=".35" stop-color="{t["a2"]}"/><stop offset="1" stop-color="{t["a2"]}" stop-opacity="0"/></linearGradient></defs>
<style>
  .i{{{ff("M", 700)};font-size:14px;fill:{t["a1"]}}}
  .t{{{ff("D", 700)};font-size:30px;fill:{t["text"]};letter-spacing:-.5px}}
  .s{{{ff("M", 400)};font-size:13px;fill:{t["muted"]}}}
  .ln{{transform-origin:0 0;transform:scaleX(0);animation:g 1.2s .2s cubic-bezier(.2,.7,.2,1) forwards}} @keyframes g{{to{{transform:scaleX(1)}}}}
  .dot{{animation:mv 3.5s ease-in-out infinite 1.4s;opacity:0}} @keyframes mv{{0%{{opacity:0;transform:translateX(0)}}10%{{opacity:1}}90%{{opacity:1}}100%{{opacity:0;transform:translateX({W - 60}px)}}}}
</style>
<rect x="2" y="16" width="34" height="26" rx="7" fill="{t["a1"]}" fill-opacity=".12" stroke="{t["a1"]}" stroke-opacity=".4"/>
<text x="19" y="34" class="i" text-anchor="middle">{e(idx)}</text>
<text x="50" y="41" class="t">{e(title)}</text>
<text x="{W - 2}" y="38" class="s" text-anchor="end">{e(sub)}</text>
<rect class="ln" x="2" y="64" width="{W - 4}" height="2" rx="1" fill="url(#hl)"/>
<circle class="dot" cx="6" cy="65" r="3.5" fill="{t["a1"]}"/>
</svg>"""


HEADERS = [
    ("01", "about", "about", "whoami --verbose"),
    ("02", "featured", "featured work", "8 systems · real metrics"),
    ("03", "toolbox", "toolbox", "what I reach for"),
    ("04", "activity", "activity", "refreshed daily by GitHub Actions"),
]


def main() -> None:
    data = fetch_stats()
    for name, t in THEMES.items():
        write("hero", name, hero(t))
        for i, b in enumerate(BUTTONS):
            write(f"btn-{b[0]}", name, button(t, *b, i))
        write("about", name, about(t))
        write("stats", name, stats(t, data))
        write("feed", name, feed(t, data))
        write("toolbox", name, toolbox(t))
        for num, slug, title, sub in HEADERS:
            write(f"h-{slug}", name, header(t, num, title, sub))
        for i, p in enumerate(PROJECTS):
            write(f"card-{p['slug']}", name, card(t, p, i))
    print(f"wrote assets for {USER}: {data['total']} contributions, {len(data['feed'])} feed commits")


if __name__ == "__main__":
    main()
