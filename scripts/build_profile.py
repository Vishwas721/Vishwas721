"""Generate the animated SVG assets for the GitHub profile README.

Run locally:   GITHUB_TOKEN=... python scripts/build_profile.py
Run in CI:     see .github/workflows/profile.yml (daily)

Every asset is written in a dark and a light variant so the README can switch
with <picture> + prefers-color-scheme. Only the stdlib is used.
"""

from __future__ import annotations

import json
import os
import urllib.request
from datetime import date, datetime, timedelta, timezone
from html import escape
from pathlib import Path

USER = os.environ.get("PROFILE_USER", "Vishwas721")
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets"

SANS = "'Segoe UI', -apple-system, BlinkMacSystemFont, 'Helvetica Neue', Helvetica, Arial, sans-serif"
MONO = "'JetBrains Mono', 'SFMono-Regular', 'Cascadia Code', Consolas, 'Liberation Mono', Menlo, monospace"

THEMES = {
    "dark": dict(
        bg="#0a0e16", panel="#0f1521", panel2="#131b2a", border="#1e2a3d", grid="#16202f",
        text="#e8eef6", muted="#8a97ab", faint="#4b5a70",
        a1="#22d3ee", a2="#a78bfa", a3="#34d399", a4="#f472b6", warn="#fbbf24",
        chip="#162033", chiptext="#b9c6d8",
    ),
    "light": dict(
        bg="#ffffff", panel="#f6f8fb", panel2="#eef2f7", border="#d6dde7", grid="#e7ecf3",
        text="#111827", muted="#556274", faint="#a3afbf",
        a1="#0891b2", a2="#7c3aed", a3="#059669", a4="#db2777", warn="#b45309",
        chip="#e9eef5", chiptext="#334155",
    ),
}

e = lambda s: escape(str(s), quote=True)  # noqa: E731


def write(name: str, theme: str, svg: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}-{theme}.svg").write_text(svg.strip() + "\n", encoding="utf-8")


def text_w(s: str, size: float, mono: bool = False) -> float:
    """Rough rendered width, good enough for layout of chips and wrapping."""
    return len(s) * size * (0.61 if mono else 0.54)


def wrap(s: str, size: float, max_w: float) -> list[str]:
    words, lines, cur = s.split(), [], ""
    for w in words:
        nxt = f"{cur} {w}".strip()
        if text_w(nxt, size) > max_w and cur:
            lines.append(cur)
            cur = w
        else:
            cur = nxt
    if cur:
        lines.append(cur)
    return lines


# --------------------------------------------------------------------------- #
# GitHub data
# --------------------------------------------------------------------------- #

QUERY = """
query($login: String!) {
  user(login: $login) {
    followers { totalCount }
    contributionsCollection {
      totalCommitContributions totalPullRequestContributions
      totalIssueContributions totalRepositoryContributions
      contributionCalendar { totalContributions
        weeks { contributionDays { date contributionCount } } }
    }
    repositories(ownerAffiliations: OWNER, first: 100, isFork: false) {
      totalCount
      nodes { stargazerCount
        languages(first: 12, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name color } } } }
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
    days = [d for w in cc["contributionCalendar"]["weeks"] for d in w["contributionDays"]]
    weeks = [sum(d["contributionCount"] for d in w["contributionDays"])
             for w in cc["contributionCalendar"]["weeks"]]

    # streaks (today with zero contributions doesn't break the current streak yet)
    counts = [d["contributionCount"] for d in days]
    longest = run = 0
    for c in counts:
        run = run + 1 if c else 0
        longest = max(longest, run)
    current, i = 0, len(counts) - 1
    if i >= 0 and counts[i] == 0:
        i -= 1
    while i >= 0 and counts[i]:
        current += 1
        i -= 1
    active_days = sum(1 for c in counts if c)
    best = max(days, key=lambda d: d["contributionCount"]) if days else {"contributionCount": 0, "date": ""}

    langs: dict[str, dict] = {}
    stars = 0
    for repo in u["repositories"]["nodes"]:
        stars += repo["stargazerCount"]
        for edge in repo["languages"]["edges"]:
            n = edge["node"]["name"]
            if n in IGNORED_LANGS:
                continue
            langs.setdefault(n, {"size": 0, "color": edge["node"]["color"] or "#888"})
            langs[n]["size"] += edge["size"]
    total = sum(v["size"] for v in langs.values()) or 1
    top = sorted(langs.items(), key=lambda kv: -kv[1]["size"])[:6]
    lang_list = [(n, v["color"], v["size"] / total) for n, v in top]

    return dict(
        total=cc["contributionCalendar"]["totalContributions"],
        commits=cc["totalCommitContributions"],
        prs=cc["totalPullRequestContributions"],
        issues=cc["totalIssueContributions"],
        new_repos=cc["totalRepositoryContributions"],
        repos=u["repositories"]["totalCount"],
        followers=u["followers"]["totalCount"],
        stars=stars,
        weeks=weeks,
        current=current, longest=longest, active_days=active_days,
        best_day=best["contributionCount"], best_date=best["date"],
        langs=lang_list,
    )


# --------------------------------------------------------------------------- #
# Hero
# --------------------------------------------------------------------------- #

def hero(t: dict) -> str:
    W, H = 1200, 400
    rotating = [
        "agentic RAG pipelines that cite their sources",
        "a transit digital twin with a Rust RAPTOR router",
        "geospatial intelligence on PostGIS + H3",
        "local-first AI that never leaves your machine",
    ]
    cycle = 3.2 * len(rotating)
    rot = []
    for i, line in enumerate(rotating):
        rot.append(
            f'<text class="rot" style="animation-delay:{i * 3.2}s" x="0" y="0">{e(line)}</text>'
        )
    # per-line visibility window inside one cycle
    frac = 100 / len(rotating)
    rot_kf = (
        f"@keyframes rot{{0%{{opacity:0;transform:translateY(10px)}}"
        f"{frac * 0.12:.1f}%{{opacity:1;transform:translateY(0)}}"
        f"{frac * 0.86:.1f}%{{opacity:1;transform:translateY(0)}}"
        f"{frac:.1f}%{{opacity:0;transform:translateY(-10px)}}100%{{opacity:0}}}}"
    )

    # pipeline graph on the right
    nodes = {
        "ingest": (760, 110), "embed": (900, 70), "graph": (900, 175),
        "agent": (1040, 125), "tools": (1050, 260), "api": (900, 290), "ui": (760, 245),
    }
    edges = [("ingest", "embed"), ("ingest", "graph"), ("embed", "agent"), ("graph", "agent"),
             ("agent", "tools"), ("tools", "api"), ("agent", "api"), ("api", "ui"), ("ui", "ingest")]
    colors = [t["a1"], t["a2"], t["a3"], t["a1"], t["a2"], t["a4"], t["a1"], t["a3"], t["a2"]]
    edge_svg, packets = [], []
    for k, ((a, b), col) in enumerate(zip(edges, colors)):
        (x1, y1), (x2, y2) = nodes[a], nodes[b]
        pid = f"p{k}"
        edge_svg.append(
            f'<path id="{pid}" d="M{x1},{y1} L{x2},{y2}" stroke="{t["border"]}" stroke-width="1.5" fill="none"/>'
            f'<path d="M{x1},{y1} L{x2},{y2}" stroke="{col}" stroke-width="1.5" fill="none" '
            f'class="flow" style="animation-delay:-{k * 0.37:.2f}s" opacity=".55"/>'
        )
        dur = 2.4 + (k % 3) * 0.6
        packets.append(
            f'<circle r="3.2" fill="{col}" filter="url(#glow)">'
            f'<animateMotion dur="{dur}s" begin="{k * 0.45:.2f}s" repeatCount="indefinite" keyPoints="0;1" keyTimes="0;1" calcMode="linear">'
            f'<mpath href="#{pid}"/></animateMotion>'
            f'<animate attributeName="opacity" values="0;1;1;0" keyTimes="0;.1;.85;1" dur="{dur}s" begin="{k * 0.45:.2f}s" repeatCount="indefinite"/>'
            f'</circle>'
        )
    node_svg = []
    for k, (name, (x, y)) in enumerate(nodes.items()):
        col = [t["a1"], t["a2"], t["a3"], t["a4"]][k % 4]
        node_svg.append(
            f'<g transform="translate({x},{y})">'
            f'<circle r="20" fill="{col}" opacity=".12" class="pulse" style="animation-delay:{k * 0.4:.1f}s"/>'
            f'<circle r="9" fill="{t["panel"]}" stroke="{col}" stroke-width="2"/>'
            f'<circle r="3.5" fill="{col}"/>'
            f'<text y="34" text-anchor="middle" class="node">{e(name)}</text></g>'
        )

    chips = [("●", "currently building Glacies", t["a3"]), ("◆", "Bengaluru, IN", t["a1"]),
             ("▲", "B.Tech ISE · CGPA 9.16", t["a2"])]
    chip_svg, cx = [], 0
    for icon, label, col in chips:
        w = text_w(label, 13, True) + 40
        icon_cls = "mono blink" if icon == "●" else "mono"
        chip_svg.append(
            f'<g transform="translate({cx},0)"><rect width="{w:.0f}" height="30" rx="15" fill="{t["chip"]}" stroke="{t["border"]}"/>'
            f'<text x="16" y="20" fill="{col}" font-size="11" class="{icon_cls}">{icon}</text>'
            f'<text x="30" y="20" class="chip">{e(label)}</text></g>'
        )
        cx += w + 10

    return f"""
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-label="Vishwas K — AI and full-stack systems engineer">
<defs>
  <pattern id="dots" width="22" height="22" patternUnits="userSpaceOnUse"><circle cx="1.5" cy="1.5" r="1.2" fill="{t["grid"]}"/></pattern>
  <linearGradient id="name" x1="0" x2="1" y1="0" y2="0">
    <stop offset="0" stop-color="{t["a1"]}"/><stop offset=".5" stop-color="{t["a2"]}"/><stop offset="1" stop-color="{t["a4"]}"/>
    <animateTransform attributeName="gradientTransform" type="translate" values="-0.4 0;0.4 0;-0.4 0" dur="9s" repeatCount="indefinite"/>
  </linearGradient>
  <radialGradient id="orb1"><stop offset="0" stop-color="{t["a2"]}" stop-opacity=".28"/><stop offset="1" stop-color="{t["a2"]}" stop-opacity="0"/></radialGradient>
  <radialGradient id="orb2"><stop offset="0" stop-color="{t["a1"]}" stop-opacity=".22"/><stop offset="1" stop-color="{t["a1"]}" stop-opacity="0"/></radialGradient>
  <linearGradient id="fade" x1="0" x2="1"><stop offset=".45" stop-color="{t["bg"]}" stop-opacity="1"/><stop offset=".62" stop-color="{t["bg"]}" stop-opacity="0"/></linearGradient>
  <filter id="glow" x="-200%" y="-200%" width="500%" height="500%"><feGaussianBlur stdDeviation="2.5" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
  <clipPath id="frame"><rect width="{W}" height="{H}" rx="22"/></clipPath>
</defs>
<style>
  text{{font-family:{SANS}}}
  .mono,.node,.chip,.prompt{{font-family:{MONO}}}
  .node{{font-size:11px;fill:{t["muted"]};letter-spacing:.5px}}
  .chip{{font-size:13px;fill:{t["chiptext"]}}}
  .prompt{{font-size:15px;fill:{t["muted"]}}}
  .name{{font-size:84px;font-weight:800;letter-spacing:-2.5px;fill:url(#name)}}
  .role{{font-size:24px;font-weight:600;fill:{t["text"]}}}
  .lead{{font-size:19px;fill:{t["muted"]}}}
  .rot{{font-size:19px;font-weight:600;fill:{t["a1"]};opacity:0;animation:rot {cycle}s infinite}}
  {rot_kf}
  .flow{{stroke-dasharray:6 14;animation:flow 1.6s linear infinite}}
  @keyframes flow{{to{{stroke-dashoffset:-40}}}}
  .pulse{{transform-box:fill-box;transform-origin:center;animation:pulse 2.8s ease-in-out infinite}}
  @keyframes pulse{{0%,100%{{transform:scale(.7);opacity:.05}}50%{{transform:scale(1.25);opacity:.22}}}}
  .cursor{{animation:blink 1s steps(1) infinite}} .blink{{animation:blink 1.6s ease-in-out infinite}}
  @keyframes blink{{50%{{opacity:0}}}}
  .orb{{animation:drift 14s ease-in-out infinite alternate}}
  @keyframes drift{{to{{transform:translate(-60px,30px)}}}}
  .rise{{opacity:0;animation:rise .9s cubic-bezier(.2,.7,.2,1) forwards}}
  @keyframes rise{{from{{opacity:0;transform:translateY(14px)}}to{{opacity:1;transform:none}}}}
</style>
<g clip-path="url(#frame)">
  <rect width="{W}" height="{H}" fill="{t["bg"]}"/>
  <rect width="{W}" height="{H}" fill="url(#dots)"/>
  <circle class="orb" cx="980" cy="120" r="300" fill="url(#orb1)"/>
  <circle class="orb" style="animation-delay:-7s" cx="260" cy="380" r="280" fill="url(#orb2)"/>
  <g>{"".join(edge_svg)}{"".join(packets)}{"".join(node_svg)}</g>
  <rect width="{W}" height="{H}" fill="url(#fade)"/>
  <g transform="translate(64,0)">
    <g class="rise" style="animation-delay:.1s"><text x="0" y="86" class="prompt"><tspan fill="{t["a3"]}">vishwas@dev</tspan><tspan fill="{t["faint"]}">:</tspan><tspan fill="{t["a1"]}">~</tspan><tspan fill="{t["faint"]}">$</tspan> whoami<tspan class="cursor" fill="{t["a1"]}"> ▋</tspan></text></g>
    <g class="rise" style="animation-delay:.3s"><text x="-4" y="172" class="name">Vishwas K</text></g>
    <g class="rise" style="animation-delay:.55s"><text x="0" y="214" class="role">AI &amp; Full-Stack Systems Engineer</text></g>
    <g class="rise" style="animation-delay:.8s">
      <text x="0" y="258" class="lead">Currently shipping</text>
      <g transform="translate(170,258)">{"".join(rot)}</g>
    </g>
    <g class="rise" style="animation-delay:1.05s"><g transform="translate(0,300)">{"".join(chip_svg)}</g></g>
  </g>
  <rect x=".5" y=".5" width="{W - 1}" height="{H - 1}" rx="22" fill="none" stroke="{t["border"]}"/>
</g>
</svg>"""


# --------------------------------------------------------------------------- #
# About (code editor window)
# --------------------------------------------------------------------------- #

def about(t: dict) -> str:
    W = 1200
    K, S, P, C, N = t["a2"], t["a3"], t["text"], t["faint"], t["a1"]  # keyword, string, plain, comment, name
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
    lh, top = 30, 78
    H = top + lh * len(lines) + 34
    body = []
    for i, segs in enumerate(lines):
        y = top + i * lh
        spans = "".join(f'<tspan fill="{col}">{e(txt)}</tspan>' for col, txt in segs)
        body.append(
            f'<g class="ln" style="animation-delay:{0.25 + i * 0.16:.2f}s">'
            f'<text x="34" y="{y}" class="num" text-anchor="end">{i + 1}</text>'
            f'<text x="62" y="{y}" class="code" xml:space="preserve">{spans}</text></g>'
        )
    last_y = top + (len(lines) - 1) * lh
    return f"""
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-label="About Vishwas: AI and full-stack systems engineer in Bengaluru, B.Tech ISE at REVA University with CGPA 9.16, Top 15 at Code Cubicle 5.0">
<style>
  .code,.num,.tab{{font-family:{MONO};font-size:17px}}
  .num{{fill:{t["faint"]};font-size:14px}}
  .tab{{font-size:13px;fill:{t["muted"]}}}
  .ln{{opacity:0;animation:ln .5s ease-out forwards}}
  @keyframes ln{{from{{opacity:0;transform:translateX(-8px)}}to{{opacity:1;transform:none}}}}
  .cur{{animation:b 1s steps(1) infinite}} @keyframes b{{50%{{opacity:0}}}}
</style>
<rect x=".5" y=".5" width="{W - 1}" height="{H - 1}" rx="16" fill="{t["panel"]}" stroke="{t["border"]}"/>
<path d="M.5 44 H{W - .5}" stroke="{t["border"]}"/>
<circle cx="26" cy="22" r="6.5" fill="#ff5f57"/><circle cx="48" cy="22" r="6.5" fill="#febc2e"/><circle cx="70" cy="22" r="6.5" fill="#28c840"/>
<rect x="96" y="8" width="150" height="36" rx="8" fill="{t["bg"]}" stroke="{t["border"]}"/>
<rect x="96" y="38" width="150" height="8" fill="{t["bg"]}"/>
<text x="114" y="31" class="tab"><tspan fill="{t["a1"]}">TS</tspan> about.ts</text>
<text x="{W - 24}" y="29" class="tab" text-anchor="end">UTF-8 · TypeScript</text>
<g transform="translate(18,0)">{"".join(body)}
<rect class="ln cur" style="animation-delay:{0.25 + len(lines) * 0.16:.2f}s" x="{62 + text_w("};", 17, True) + 4:.0f}" y="{last_y - 15}" width="9" height="20" fill="{t["a1"]}"/></g>
</svg>"""


# --------------------------------------------------------------------------- #
# Stats
# --------------------------------------------------------------------------- #

def stats(t: dict, s: dict) -> str:
    W, H = 1200, 330
    tiles = [
        (f'{s["total"]:,}', "contributions", "last 12 months", t["a1"]),
        (f'{s["commits"]:,}', "commits", f'{s["active_days"]} active days', t["a2"]),
        (f'{s["prs"]:,}', "pull requests", f'{s["issues"]} issues opened', t["a3"]),
        (f'{s["current"]}d', "current streak", f'longest {s["longest"]} days', t["a4"]),
    ]
    tw = (W - 48 - 3 * 16) / 4
    tile_svg = []
    for i, (val, label, sub, col) in enumerate(tiles):
        x = 24 + i * (tw + 16)
        tile_svg.append(
            f'<g class="up" style="animation-delay:{0.1 + i * 0.12:.2f}s"><g transform="translate({x:.1f},24)">'
            f'<rect width="{tw:.1f}" height="104" rx="14" fill="{t["panel2"]}" stroke="{t["border"]}"/>'
            f'<rect x="18" y="0" width="34" height="3" rx="1.5" fill="{col}"/>'
            f'<text x="18" y="54" class="val" fill="{col}">{e(val)}</text>'
            f'<text x="18" y="76" class="lbl">{e(label)}</text>'
            f'<text x="18" y="94" class="sub">{e(sub)}</text></g></g>'
        )

    # weekly sparkline
    weeks = s["weeks"][-52:] or [0]
    gx, gy, gw, gh = 24, 160, 740, 120
    mx = max(weeks) or 1
    step = gw / max(len(weeks) - 1, 1)
    pts = [(gx + i * step, gy + gh - (v / mx) * (gh - 10)) for i, v in enumerate(weeks)]
    d = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    area = d + f" L{gx + gw:.1f},{gy + gh} L{gx},{gy + gh} Z"
    peak_i = max(range(len(weeks)), key=lambda i: weeks[i])
    px, py = pts[peak_i]
    grid = "".join(
        f'<path d="M{gx} {gy + gh * f:.1f} H{gx + gw}" stroke="{t["grid"]}" stroke-dasharray="3 5"/>'
        for f in (0, 0.5, 1)
    )

    # language bar
    lx, ly, lw = 800, 172, 376
    bar, legend, acc = [], [], 0.0
    for i, (name, color, frac) in enumerate(s["langs"]):
        w = lw * frac
        bar.append(f'<rect x="{lx + acc:.1f}" y="{ly}" width="{max(w - 2, 1):.1f}" height="12" fill="{color}"/>')
        acc += w
        col_x = lx + (i % 2) * 190
        row_y = ly + 42 + (i // 2) * 28
        legend.append(
            f'<g class="up" style="animation-delay:{0.6 + i * 0.08:.2f}s">'
            f'<circle cx="{col_x + 6}" cy="{row_y - 5}" r="5.5" fill="{color}"/>'
            f'<text x="{col_x + 20}" y="{row_y}" class="lang">{e(name)}</text>'
            f'<text x="{col_x + 176}" y="{row_y}" class="pct" text-anchor="end">{frac * 100:.1f}%</text></g>'
        )
    total_frac = sum(f for _, _, f in s["langs"]) or 1
    acc_scale = lw / (lw * total_frac)
    updated = datetime.now(timezone.utc).strftime("%d %b %Y")

    return f"""
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-label="GitHub activity: {s["total"]} contributions, {s["commits"]} commits, {s["prs"]} pull requests in the last year">
<defs>
  <linearGradient id="ar" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="{t["a1"]}" stop-opacity=".35"/><stop offset="1" stop-color="{t["a1"]}" stop-opacity="0"/></linearGradient>
  <linearGradient id="ln" x1="0" x2="1"><stop offset="0" stop-color="{t["a2"]}"/><stop offset="1" stop-color="{t["a1"]}"/></linearGradient>
  <clipPath id="bar"><rect x="{lx}" y="{ly}" width="{lw}" height="12" rx="6"/></clipPath>
</defs>
<style>
  text{{font-family:{SANS}}}
  .val{{font-size:36px;font-weight:800;letter-spacing:-1px}}
  .lbl{{font-size:15px;font-weight:600;fill:{t["text"]}}}
  .sub,.cap,.pct{{font-family:{MONO};font-size:12px;fill:{t["muted"]}}}
  .lang{{font-size:14px;fill:{t["text"]}}}
  .h{{font-size:13px;font-weight:700;fill:{t["muted"]};letter-spacing:1.6px}}
  .up{{opacity:0;animation:up .7s cubic-bezier(.2,.7,.2,1) forwards}}
  @keyframes up{{from{{opacity:0;transform:translateY(10px)}}to{{opacity:1;transform:none}}}}
  .draw{{stroke-dasharray:3000;stroke-dashoffset:3000;animation:draw 2.6s .4s ease-out forwards}}
  @keyframes draw{{to{{stroke-dashoffset:0}}}}
  .fill{{opacity:0;animation:fi 1s 1.8s forwards}} @keyframes fi{{to{{opacity:1}}}}
  .grow{{transform-origin:{lx}px 0;transform:scaleX(0);animation:grow 1.4s .5s cubic-bezier(.2,.7,.2,1) forwards}}
  @keyframes grow{{to{{transform:scaleX({acc_scale:.4f})}}}}
  .ping{{transform-box:fill-box;transform-origin:center;animation:ping 2s ease-out infinite 2.6s;opacity:0}}
  @keyframes ping{{0%{{transform:scale(.6);opacity:.8}}100%{{transform:scale(2.6);opacity:0}}}}
</style>
<rect x=".5" y=".5" width="{W - 1}" height="{H - 1}" rx="18" fill="{t["panel"]}" stroke="{t["border"]}"/>
{"".join(tile_svg)}
<text x="{gx}" y="{gy - 10}" class="h">WEEKLY CONTRIBUTIONS</text>
<text x="{gx + gw}" y="{gy - 10}" class="cap" text-anchor="end">peak {weeks[peak_i]} / week · best day {s["best_day"]}</text>
{grid}
<path d="{area}" fill="url(#ar)" class="fill"/>
<path d="{d}" fill="none" stroke="url(#ln)" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round" class="draw"/>
<circle cx="{px:.1f}" cy="{py:.1f}" r="6" fill="{t["a1"]}" class="ping"/>
<circle cx="{px:.1f}" cy="{py:.1f}" r="4" fill="{t["a1"]}" class="fill"/>
<path d="M{lx - 18} 140 V{H - 24}" stroke="{t["border"]}"/>
<text x="{lx}" y="{gy - 10}" class="h">LANGUAGES</text>
<text x="{lx + lw}" y="{gy - 10}" class="cap" text-anchor="end">{s["repos"]} repos</text>
<g clip-path="url(#bar)"><rect x="{lx}" y="{ly}" width="{lw}" height="12" fill="{t["grid"]}"/><g class="grow">{"".join(bar)}</g></g>
{"".join(legend)}
<text x="{W - 24}" y="{H - 14}" class="cap" text-anchor="end" opacity=".7">auto-updated {updated}</text>
</svg>"""


# --------------------------------------------------------------------------- #
# Project cards
# --------------------------------------------------------------------------- #

PROJECTS = [
    dict(slug="glacies", name="Glacies", kind="Urban transit digital twin",
         status=("BUILDING", "a3"), accent="a1",
         blurb="Models a city's transit network from open data, generates synthetic demand and answers “what if we changed the network?” — starting with Bengaluru.",
         metric=("GTFS + OSM", "→ Rust RAPTOR → scenarios"),
         stack=["Rust", "Python", "TypeScript", "Docker"]),
    dict(slug="summaid", name="SummAID", kind="On-prem medical intelligence",
         status=("SHIPPED", "a1"), accent="a3",
         blurb="Hybrid RAG over encrypted patient records with a “Glass Box” citation system linking every claim back to its source page.",
         metric=("12 min → <50 s", "clinical review time"),
         stack=["Python", "FastAPI", "pgvector", "LangChain"]),
    dict(slug="privex", name="Privex", kind="Agentic visual firewall + memory",
         status=("SHIPPED", "a1"), accent="a2",
         blurb="Redacts credentials from live meetings with YOLOv8 + OCR, and remembers context through a vector + Neo4j graph memory orchestrated by LangGraph.",
         metric=("Vector + Graph", "multi-hop hybrid memory"),
         stack=["LangGraph", "YOLOv8", "Neo4j", "MCP"]),
    dict(slug="qnit", name="Qnit", kind="Cited site intelligence for India",
         status=("LIVE", "a3"), accent="a4",
         blurb="Draw a site, get flood, sun path, wind, zoning and infrastructure context — every number cited with source, version and date, exportable to a bank-grade PDF.",
         metric=("₹20k–50k", "consultant work, automated"),
         stack=["Next.js 16", "React 19", "Python", "Leaflet"]),
    dict(slug="preuve", name="Preuve", kind="Evidence-driven idea validation",
         status=("BUILDING", "a3"), accent="a1",
         blurb="Validates startup ideas by finding people who actually have the problem and measuring behaviour and commitment, not opinions.",
         metric=("Hybrid LLM", "local Ollama + Gemini"),
         stack=["FastAPI", "Next.js", "Redis", "SearXNG"]),
    dict(slug="panenka", name="Panenka", kind="Local-first football analytics",
         status=("SHIPPED", "a1"), accent="a3",
         blurb="Private match and player analytics workspace on local Postgres, with a Model Context Protocol server so AI agents can query the stats.",
         metric=("109 tests", "passing · strict TypeScript"),
         stack=["Next.js", "Prisma", "PostgreSQL", "MCP"]),
    dict(slug="klados", name="Klados", kind="Lead discovery engine",
         status=("LIVE", "a3"), accent="a2",
         blurb="Sweeps cities cell by cell on an H3 grid, audits every business website in a stealth browser and turns the gaps into ready-to-send pitches.",
         metric=("H3 res-9", "grid scanning + site audits"),
         stack=["FastAPI", "Redis/RQ", "Camoufox", "Ollama"]),
    dict(slug="nagarikone", name="NagarikOne", kind="Geospatial civic reporting",
         status=("PILOTED", "a1"), accent="a4",
         blurb="Citizens report civic issues; PostGIS auto-merges duplicates within a 50 m radius. Validated on a live pilot across Bengaluru.",
         metric=("50 m · <5 s", "geo-dedupe latency"),
         stack=["React Native", "PostGIS", "Node.js", "Vercel"]),
]


def card(t: dict, p: dict, idx: int) -> str:
    W, H = 580, 300
    acc = t[p["accent"]]
    st_label, st_col = p["status"][0], t[p["status"][1]]
    lines = wrap(p["blurb"], 15, W - 56)[:3]
    blurb = "".join(f'<text x="28" y="{122 + i * 22}" class="b">{e(l)}</text>' for i, l in enumerate(lines))
    chips, cx = [], 28
    for s in p["stack"]:
        w = text_w(s, 12, True) + 22
        chips.append(f'<g transform="translate({cx:.0f},{H - 50})"><rect width="{w:.0f}" height="26" rx="7" fill="{t["chip"]}" stroke="{t["border"]}"/>'
                     f'<text x="11" y="17.5" class="c">{e(s)}</text></g>')
        cx += w + 8
    sw = text_w(st_label, 11, True) + 30
    gid = f"g{idx}"
    return f"""
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-label="{e(p["name"])}: {e(p["kind"])}">
<defs>
  <radialGradient id="{gid}" cx="1" cy="0" r="1"><stop offset="0" stop-color="{acc}" stop-opacity=".22"/><stop offset=".6" stop-color="{acc}" stop-opacity="0"/></radialGradient>
  <linearGradient id="s{gid}" x1="0" x2="1"><stop offset="0" stop-color="{acc}" stop-opacity="0"/><stop offset=".5" stop-color="{acc}"/><stop offset="1" stop-color="{acc}" stop-opacity="0"/></linearGradient>
  <clipPath id="c{gid}"><rect width="{W}" height="{H}" rx="18"/></clipPath>
</defs>
<style>
  text{{font-family:{SANS}}}
  .t{{font-size:30px;font-weight:800;fill:{t["text"]};letter-spacing:-.6px}}
  .k{{font-family:{MONO};font-size:12.5px;fill:{acc};letter-spacing:1.2px}}
  .b{{font-size:15px;fill:{t["muted"]}}}
  .c,.st{{font-family:{MONO};font-size:12px;fill:{t["chiptext"]}}}
  .st{{font-size:11px;font-weight:700;letter-spacing:1px;fill:{st_col}}}
  .mv{{font-size:22px;font-weight:800;fill:{acc}}}
  .ml{{font-family:{MONO};font-size:12.5px;fill:{t["muted"]}}}
  .scan{{animation:scan 5s ease-in-out infinite;animation-delay:{idx * 0.6:.1f}s}}
  @keyframes scan{{0%{{transform:translateX(-{W}px)}}60%,100%{{transform:translateX({W}px)}}}}
  .dot{{animation:d 1.8s ease-in-out infinite}} @keyframes d{{50%{{opacity:.25}}}}
</style>
<g clip-path="url(#c{gid})">
  <rect width="{W}" height="{H}" fill="{t["panel"]}"/>
  <rect width="{W}" height="{H}" fill="url(#{gid})"/>
  <rect class="scan" x="0" y="0" width="{W}" height="2" fill="url(#s{gid})"/>
  <rect x="0" y="0" width="5" height="{H}" fill="{acc}" opacity=".85"/>
</g>
<rect x=".5" y=".5" width="{W - 1}" height="{H - 1}" rx="18" fill="none" stroke="{t["border"]}"/>
<text x="28" y="46" class="k">{e(p["kind"].upper())}</text>
<g transform="translate({W - 24 - sw:.0f},28)"><rect width="{sw:.0f}" height="24" rx="12" fill="none" stroke="{st_col}" stroke-opacity=".5"/>
<circle class="dot" cx="13" cy="12" r="3.5" fill="{st_col}"/><text x="22" y="16" class="st">{e(st_label)}</text></g>
<text x="28" y="88" class="t">{e(p["name"])}</text>
{blurb}
<text x="28" y="{H - 72}" class="mv">{e(p["metric"][0])}</text>
<text x="{36 + text_w(p["metric"][0], 22) * 1.05:.0f}" y="{H - 72}" class="ml">{e(p["metric"][1])}</text>
{"".join(chips)}
</svg>"""


# --------------------------------------------------------------------------- #
# Toolbox (the parts icon sets don't cover)
# --------------------------------------------------------------------------- #

TOOLBOX = [
    ("AGENTS & LLMs", "a2", ["LangGraph", "LangChain", "MCP", "Ollama", "Gemini", "Pydantic"]),
    ("RETRIEVAL & DATA", "a1", ["pgvector", "Neo4j", "PostgreSQL", "Redis", "SQLAlchemy", "Prisma"]),
    ("GEO & VISION", "a3", ["PostGIS", "H3", "GTFS", "Leaflet", "YOLOv8", "EasyOCR"]),
    ("SYSTEMS", "a4", ["Rust", "FastAPI", "Docker", "Playwright", "arq / RQ", "Actions"]),
]


def toolbox(t: dict) -> str:
    W, rowh = 1200, 56
    H = 28 + rowh * len(TOOLBOX) + 12
    rows = []
    for r, (label, ak, items) in enumerate(TOOLBOX):
        y = 28 + r * rowh
        col = t[ak]
        chips, cx = [], 250
        for i, s in enumerate(items):
            w = text_w(s, 14, True) + 30
            chips.append(
                f'<g class="pop" style="animation-delay:{0.15 + r * 0.12 + i * 0.05:.2f}s"><g transform="translate({cx:.0f},{y})">'
                f'<rect width="{w:.0f}" height="34" rx="9" fill="{t["chip"]}" stroke="{t["border"]}"/>'
                f'<circle cx="13" cy="17" r="3" fill="{col}"/>'
                f'<text x="22" y="22" class="c">{e(s)}</text></g></g>'
            )
            cx += w + 10
        rows.append(
            f'<text x="28" y="{y + 22}" class="l" fill="{col}">{e(label)}</text>{"".join(chips)}'
        )
    return f"""
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-label="Toolbox: {e(", ".join(x for _, _, it in TOOLBOX for x in it))}">
<style>
  .l{{font-family:{MONO};font-size:13px;font-weight:700;letter-spacing:1.4px}}
  .c{{font-family:{MONO};font-size:14px;fill:{t["chiptext"]}}}
  .pop{{opacity:0;animation:pop .5s cubic-bezier(.2,.7,.2,1) forwards}}
  @keyframes pop{{from{{opacity:0;transform:translateY(6px)}}to{{opacity:1;transform:none}}}}
</style>
<rect x=".5" y=".5" width="{W - 1}" height="{H - 1}" rx="18" fill="{t["panel"]}" stroke="{t["border"]}"/>
{"".join(rows)}
</svg>"""


# --------------------------------------------------------------------------- #
# Section headers
# --------------------------------------------------------------------------- #

def header(t: dict, idx: str, title: str, sub: str) -> str:
    W, H = 1200, 70
    return f"""
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-label="{e(title)}">
<defs><linearGradient id="hl" x1="0" x2="1"><stop offset="0" stop-color="{t["a1"]}"/><stop offset=".35" stop-color="{t["a2"]}"/><stop offset="1" stop-color="{t["a2"]}" stop-opacity="0"/></linearGradient></defs>
<style>
  .i{{font-family:{MONO};font-size:15px;fill:{t["a1"]}}}
  .t{{font-family:{SANS};font-size:28px;font-weight:800;fill:{t["text"]};letter-spacing:-.4px}}
  .s{{font-family:{MONO};font-size:13px;fill:{t["muted"]}}}
  .ln{{transform-origin:0 0;transform:scaleX(0);animation:g 1.2s .2s cubic-bezier(.2,.7,.2,1) forwards}}
  @keyframes g{{to{{transform:scaleX(1)}}}}
</style>
<text x="2" y="38" class="i">{e(idx)}</text>
<text x="44" y="40" class="t">{e(title)}</text>
<text x="{W - 2}" y="38" class="s" text-anchor="end">{e(sub)}</text>
<rect class="ln" x="2" y="60" width="{W - 4}" height="2" rx="1" fill="url(#hl)"/>
</svg>"""


HEADERS = [
    ("01", "about", "whoami --verbose"),
    ("02", "featured work", "8 systems, real metrics"),
    ("03", "toolbox", "what I reach for"),
    ("04", "activity", "refreshed daily by GitHub Actions"),
]


def main() -> None:
    data = fetch_stats()
    for name, t in THEMES.items():
        write("hero", name, hero(t))
        write("about", name, about(t))
        write("stats", name, stats(t, data))
        write("toolbox", name, toolbox(t))
        for num, title, sub in HEADERS:
            write(f"h-{title.split()[0]}", name, header(t, num, title, sub))
        for i, p in enumerate(PROJECTS):
            write(f"card-{p['slug']}", name, card(t, p, i))
    print(f"wrote assets for {USER}: {data['total']} contributions, streak {data['current']}d")


if __name__ == "__main__":
    main()
