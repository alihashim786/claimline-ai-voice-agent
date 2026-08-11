"""
ClaimLine AI — public dashboard.

A single-page Streamlit app that doubles as the product landing page for the
ClaimLine AI voice agent:

  * embeds the live Retell website widget so a visitor can talk to the agent
  * mirrors the Claims tab of the Google Sheet the agent writes to
  * charts claim mix, urgency split and volume over time
  * offers a read-only claim lookup (the same thing the voice agent does)

Everything the agent writes lands in Google Sheets; this app only ever reads.

Streamlit note: this whole file re-executes top to bottom on every interaction
(button click, text input, tab switch). That is why every expensive thing —
the Google credentials handshake, the Sheets read — sits behind a cache
decorator. Without them you would re-authenticate against Google on every
keystroke in the lookup box and get rate-limited within a minute.
"""

from __future__ import annotations

import json
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# --------------------------------------------------------------------------
# Design tokens
#
# One place for every colour. The two chart hues were validated as a
# categorical pair against the #fcfcfb chart surface: normal-vision ΔE 31.6,
# worst colour-vision-deficiency ΔE 23.8 (protan) — comfortably clear of the
# ΔE 15 / ΔE 8 floors, so the urgency split stays readable for colourblind
# viewers and in greyscale print.
# --------------------------------------------------------------------------
INK = "#0b0b0b"
INK_SOFT = "#52514e"
INK_MUTED = "#898781"
SURFACE = "#fcfcfb"
PLANE = "#f9f9f7"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"

BRAND_DEEP = "#0f3d5c"
BRAND_MID = "#12557f"
BRAND_ACCENT = "#2a78d6"

SERIES_BLUE = "#2a78d6"
STATUS_CRITICAL = "#d03b3b"
STATUS_GOOD = "#0ca30c"
STATUS_WARNING = "#fab219"

FONT_STACK = 'system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif'

CLAIM_COLUMNS = [
    "claim_id",
    "policy_number",
    "holder_name",
    "incident_type",
    "incident_date",
    "description",
    "urgency",
    "status",
    "email",
    "created_at",
]

CACHE_TTL_SECONDS = 45  # short enough to feel live, long enough to stay well
# inside the Google Sheets API free read quota.

st.set_page_config(
    page_title="ClaimLine AI — Voice Claims Intake & Triage",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# --------------------------------------------------------------------------
# Styling
# --------------------------------------------------------------------------
def inject_css() -> None:
    """Replace Streamlit's default widget look with a product landing page.

    Streamlit ships a recognisable default skin (thin grey borders, red
    accents, the running-man toolbar). Left alone, the page reads as
    "somebody's Streamlit script" rather than a product, so we hide the chrome
    and restyle the primitives we actually use.
    """
    st.markdown(
        f"""
        <style>
          /* ---- kill the default Streamlit chrome -------------------- */
          #MainMenu, header[data-testid="stHeader"], footer {{ visibility: hidden; }}
          [data-testid="stToolbar"], [data-testid="stDecoration"] {{ display: none; }}
          .block-container {{ padding: 0 1.6rem 4rem; max-width: 1180px; }}
          .stApp {{ background: {PLANE}; }}

          html, body, [class*="css"] {{
            font-family: {FONT_STACK};
            color: {INK};
          }}

          /* ---- hero ------------------------------------------------- */
          .cl-hero {{
            position: relative;
            margin: 0 -1.6rem 2.4rem;
            padding: 4.2rem 3rem 3.4rem;
            background:
              radial-gradient(900px 380px at 82% -8%, rgba(42,120,214,.42), transparent 62%),
              linear-gradient(155deg, {BRAND_DEEP} 0%, #0b2d45 55%, #08202f 100%);
            color: #fff;
            overflow: hidden;
          }}
          .cl-hero::after {{
            content: "";
            position: absolute; inset: 0;
            background-image:
              linear-gradient(rgba(255,255,255,.05) 1px, transparent 1px),
              linear-gradient(90deg, rgba(255,255,255,.05) 1px, transparent 1px);
            background-size: 46px 46px;
            mask-image: radial-gradient(700px 340px at 20% 0%, #000, transparent 72%);
            pointer-events: none;
          }}
          .cl-hero-inner {{ position: relative; z-index: 1; max-width: 720px; }}
          .cl-eyebrow {{
            display: inline-flex; align-items: center; gap: .5rem;
            font-size: .74rem; font-weight: 700; letter-spacing: .1em;
            text-transform: uppercase; color: #9fc6dd;
            border: 1px solid rgba(159,198,221,.34);
            border-radius: 999px; padding: .34rem .82rem; margin-bottom: 1.3rem;
          }}
          .cl-dot {{
            width: 7px; height: 7px; border-radius: 50%;
            background: #52e08a; box-shadow: 0 0 0 3px rgba(82,224,138,.22);
          }}
          .cl-hero h1 {{
            font-size: clamp(2.1rem, 4.4vw, 3.35rem);
            line-height: 1.06; letter-spacing: -.028em;
            font-weight: 800; margin: 0 0 1.05rem; color: #fff;
          }}
          .cl-hero h1 em {{
            font-style: normal;
            background: linear-gradient(96deg, #7fd0ff, #b9e6ff);
            -webkit-background-clip: text; background-clip: text;
            -webkit-text-fill-color: transparent;
          }}
          .cl-hero p {{
            font-size: 1.06rem; line-height: 1.62;
            color: rgba(255,255,255,.8); margin: 0 0 1.7rem; max-width: 620px;
          }}
          .cl-pills {{ display: flex; flex-wrap: wrap; gap: .55rem; }}
          .cl-pill {{
            font-size: .79rem; font-weight: 600; color: rgba(255,255,255,.9);
            background: rgba(255,255,255,.09);
            border: 1px solid rgba(255,255,255,.14);
            border-radius: 8px; padding: .42rem .78rem;
          }}

          /* ---- section headings ------------------------------------- */
          .cl-section {{ margin: 2.6rem 0 1.1rem; }}
          .cl-kicker {{
            font-size: .72rem; font-weight: 700; letter-spacing: .12em;
            text-transform: uppercase; color: {BRAND_ACCENT}; margin-bottom: .38rem;
          }}
          .cl-section h2 {{
            font-size: 1.42rem; font-weight: 700; letter-spacing: -.018em;
            margin: 0 0 .3rem; color: {INK};
          }}
          .cl-section p {{ font-size: .93rem; color: {INK_SOFT}; margin: 0; max-width: 640px; }}

          /* ---- cards & tiles ---------------------------------------- */
          .cl-card {{
            background: {SURFACE};
            border: 1px solid rgba(11,11,11,.10);
            border-radius: 14px; padding: 1.35rem 1.5rem;
            box-shadow: 0 1px 2px rgba(11,11,11,.04);
          }}
          .cl-tile {{
            background: {SURFACE};
            border: 1px solid rgba(11,11,11,.10);
            border-radius: 14px; padding: 1.15rem 1.3rem; height: 100%;
            box-shadow: 0 1px 2px rgba(11,11,11,.04);
          }}
          .cl-tile-label {{
            font-size: .74rem; font-weight: 700; letter-spacing: .07em;
            text-transform: uppercase; color: {INK_MUTED}; margin-bottom: .5rem;
          }}
          .cl-tile-value {{
            font-size: 2.15rem; font-weight: 800; letter-spacing: -.03em;
            line-height: 1; color: {INK};
          }}
          .cl-tile-sub {{ font-size: .82rem; color: {INK_SOFT}; margin-top: .45rem; }}
          .cl-tile-value.is-critical {{ color: {STATUS_CRITICAL}; }}

          /* ---- misc ------------------------------------------------- */
          /* ---- live call panel -------------------------------------- */
          .cl-call {{
            background: {SURFACE};
            border: 1px solid rgba(11,11,11,.10);
            border-radius: 14px; padding: 1rem 1.2rem; margin-top: .7rem;
            box-shadow: 0 1px 2px rgba(11,11,11,.04);
          }}
          .cl-call-row {{ display: flex; align-items: center; gap: .7rem; }}
          .cl-call-dot {{
            width: 10px; height: 10px; border-radius: 50%;
            background: {INK_MUTED}; flex: none;
          }}
          .cl-call-dot.is-connecting {{
            background: {STATUS_WARNING};
            animation: cl-pulse 1.1s ease-in-out infinite;
          }}
          .cl-call-dot.is-live {{
            background: {STATUS_GOOD};
            box-shadow: 0 0 0 4px rgba(12,163,12,.16);
            animation: cl-pulse 1.6s ease-in-out infinite;
          }}
          .cl-call-dot.is-ended {{ background: {INK_MUTED}; }}
          .cl-call-dot.is-error {{ background: {STATUS_CRITICAL}; }}
          @keyframes cl-pulse {{
            0%,100% {{ opacity: 1; }} 50% {{ opacity: .35; }}
          }}
          .cl-call-status {{ font-size: .92rem; font-weight: 600; color: {INK}; flex: 1; }}
          .cl-call-end {{
            background: {STATUS_CRITICAL}; color: #fff; border: none;
            border-radius: 8px; padding: .4rem .9rem; font-size: .84rem;
            font-weight: 600; cursor: pointer; font-family: inherit;
          }}
          .cl-call-end:hover {{ background: #b32f2f; }}
          .cl-call-node {{
            font-size: .78rem; color: {INK_MUTED}; margin-top: .45rem;
            font-family: ui-monospace, Consolas, monospace;
          }}
          .cl-call-err {{ font-size: .84rem; color: {STATUS_CRITICAL}; margin-top: .45rem; }}

          /* ---- chart cards ------------------------------------------ */
          /* The chart itself is the card. An HTML wrapper div cannot work
             here: Streamlit renders each element as a sibling, so a <div>
             opened in st.markdown is closed before st.plotly_chart runs and
             you get an empty box with the chart floating underneath it. */
          .cl-chart-head {{ margin: 0 0 .5rem; }}
          .cl-chart-head .t {{ font-weight: 700; font-size: .95rem; color: {INK}; }}
          .cl-chart-head .s {{ font-size: .82rem; color: {INK_MUTED}; margin-top: .1rem; }}
          div[data-testid="stPlotlyChart"] {{
            background: {SURFACE};
            border: 1px solid rgba(11,11,11,.10);
            border-radius: 14px;
            padding: .9rem 1rem;
            box-shadow: 0 1px 2px rgba(11,11,11,.04);
            overflow: hidden;
          }}

          .cl-note {{
            font-size: .83rem; color: {INK_SOFT}; line-height: 1.6;
            background: #fffbeb; border: 1px solid #fde68a;
            border-radius: 10px; padding: .8rem 1rem;
          }}
          .cl-kv {{ display: flex; justify-content: space-between; gap: 1rem;
                   padding: .62rem 0; border-bottom: 1px solid #f0f1f3; font-size: .92rem; }}
          .cl-kv:last-child {{ border-bottom: none; }}
          .cl-kv span:first-child {{ color: {INK_MUTED}; }}
          .cl-kv span:last-child {{ font-weight: 600; text-align: right; }}
          .cl-badge {{
            display: inline-block; font-size: .74rem; font-weight: 700;
            border-radius: 999px; padding: .2rem .62rem;
          }}
          .cl-badge.urgent {{ background: rgba(208,59,59,.12); color: {STATUS_CRITICAL}; }}
          .cl-badge.standard {{ background: rgba(42,120,214,.12); color: {SERIES_BLUE}; }}

          .cl-footer {{
            margin-top: 3.4rem; padding-top: 1.5rem;
            border-top: 1px solid {GRID};
            font-size: .85rem; color: {INK_SOFT}; line-height: 1.7;
          }}
          .cl-footer a {{ color: {BRAND_ACCENT}; text-decoration: none; font-weight: 600; }}

          /* ---- restyled Streamlit primitives ------------------------ */
          .stButton > button {{
            background: {BRAND_MID}; color: #fff; border: none;
            border-radius: 9px; padding: .55rem 1.15rem;
            font-weight: 600; font-size: .9rem; transition: background .15s ease;
          }}
          .stButton > button:hover {{ background: {BRAND_DEEP}; color: #fff; }}
          .stTextInput input {{
            border-radius: 9px; border: 1px solid rgba(11,11,11,.16);
            padding: .6rem .8rem; font-size: .95rem;
          }}
          .stTextInput input:focus {{
            border-color: {BRAND_ACCENT};
            box-shadow: 0 0 0 3px rgba(42,120,214,.16);
          }}
          [data-testid="stDataFrame"] {{
            border: 1px solid rgba(11,11,11,.10); border-radius: 12px; overflow: hidden;
          }}
          div[data-baseweb="tab-list"] {{ gap: .35rem; border-bottom: 1px solid {GRID}; }}
          button[data-baseweb="tab"] {{ font-weight: 600; font-size: .92rem; }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def section(kicker: str, title: str, blurb: str = "") -> None:
    st.markdown(
        f"""<div class="cl-section">
              <div class="cl-kicker">{kicker}</div>
              <h2>{title}</h2>
              {f"<p>{blurb}</p>" if blurb else ""}
            </div>""",
        unsafe_allow_html=True,
    )


def tile(label: str, value: str, sub: str = "", critical: bool = False) -> str:
    cls = "cl-tile-value is-critical" if critical else "cl-tile-value"
    return (
        f'<div class="cl-tile"><div class="cl-tile-label">{label}</div>'
        f'<div class="{cls}">{value}</div>'
        f'{f"<div class=cl-tile-sub>{sub}</div>" if sub else ""}</div>'
    )


# --------------------------------------------------------------------------
# Secrets
# --------------------------------------------------------------------------
def secret(section_name: str, key: str, default: str = "") -> str:
    """Read a nested secret without ever raising.

    Touching `st.secrets` at all when no secrets file exists raises in
    Streamlit, so a bare `st.secrets.get(...)` is not the safe call it looks
    like. This wrapper lets a fresh clone with no secrets render the page and
    show a setup notice instead of a stack trace.
    """
    try:
        return str(st.secrets[section_name][key])
    except Exception:
        return default


# --------------------------------------------------------------------------
# Retell website widget
# --------------------------------------------------------------------------
RETELL_SDK = "https://esm.sh/retell-client-js-sdk@2.0.8"


def create_web_call(api_key: str, agent_id: str) -> dict:
    """Register a web call with Retell and return its short-lived access token.

    This runs SERVER-SIDE, inside Streamlit's Python process. That is the whole
    point: the Retell *private* API key never leaves the server, and the browser
    only ever receives a scoped, ~10-minute LiveKit token that can join exactly
    one call room and do nothing else.

    Why this exists at all: Retell's `retell-widget.js` — the "just add a script
    tag with your public key" option — is a **chat** widget. Its bundle contains
    no WebRTC, no getUserMedia and no audio handling, so it cannot place a voice
    call however it is configured. Browser voice requires the client SDK plus a
    token minted with the private key, which means a server. Streamlit is that
    server.

    Not cached: a token is single-use and time-limited, so every call gets a
    fresh one, minted at the moment the visitor clicks.
    """
    import urllib.request

    req = urllib.request.Request(
        "https://api.retellai.com/v2/create-web-call",
        data=json.dumps({"agent_id": agent_id}).encode(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def render_voice_call(access_token: str, call_id: str) -> None:
    """Run the live call in the page via retell-client-js-sdk.

    Rendered with `st.html(..., unsafe_allow_javascript=True)`, which injects
    into the **top-level document** rather than an iframe. That matters twice
    over: microphone permission belongs to the real page instead of needing to
    be delegated into a frame, and nothing gets clipped by a short iframe.

    Streamlit re-runs this whole script on every interaction, so the SDK client
    is parked on `window` and keyed by call_id. A re-run re-binds the UI to the
    *existing* client instead of starting a second, overlapping call.

    There is deliberately no `st.components.v1.html` fallback here. That renders
    into an iframe, and Streamlit's component iframes do not list `microphone`
    in their `allow` attribute — so the browser blocks getUserMedia and the call
    can never connect. Falling back to it would produce a call button that fails
    for a reason nobody could see. Requiring a new enough Streamlit is the
    honest option, which is why requirements.txt floors it.
    """
    markup = f"""
<div id="cl-call" class="cl-call">
  <div class="cl-call-row">
    <span id="cl-dot" class="cl-call-dot"></span>
    <span id="cl-status" class="cl-call-status">Connecting&hellip;</span>
    <button id="cl-end" class="cl-call-end">End call</button>
  </div>
  <div id="cl-node" class="cl-call-node"></div>
  <div id="cl-err" class="cl-call-err"></div>
</div>

<script type="module">
import {{ RetellWebClient }} from "{RETELL_SDK}";

const CALL_ID = {json.dumps(call_id)};
const TOKEN   = {json.dumps(access_token)};

const $ = (id) => document.getElementById(id);

function paint(state, text) {{
  const dot = $("cl-dot"), status = $("cl-status"), end = $("cl-end");
  if (!dot) return;
  dot.className = "cl-call-dot is-" + state;
  status.textContent = text;
  end.style.display = (state === "live" || state === "connecting") ? "" : "none";
}}

function bind(client) {{
  const end = $("cl-end");
  if (end) end.onclick = () => {{ try {{ client.stopCall(); }} catch (e) {{}} paint("ended", "Call ended"); }};

  client.on("call_started",       () => paint("live", "Connected \\u2014 start speaking"));
  client.on("call_ready",         () => paint("live", "Connected \\u2014 start speaking"));
  client.on("agent_start_talking",() => paint("live", "ClaimLine AI is speaking\\u2026"));
  client.on("agent_stop_talking", () => paint("live", "Listening\\u2026"));
  client.on("call_ended",         () => paint("ended", "Call ended"));

  // The agent is a node graph, so we can show which node it is in as the
  // conversation branches. Nice to watch the flow route in real time.
  client.on("node_transition", (e) => {{
    const n = $("cl-node");
    if (n && e && e.new_node_name) n.textContent = "Flow node: " + e.new_node_name;
  }});

  client.on("error", (e) => {{
    paint("error", "Call error");
    const box = $("cl-err");
    if (box) box.textContent = (e && (e.message || e.error)) || "Unknown error from the voice SDK.";
    try {{ client.stopCall(); }} catch (_) {{}}
  }});
}}

if (window.__clClient && window.__clCallId === CALL_ID) {{
  // A Streamlit re-run redrew this block; the call is already running.
  bind(window.__clClient);
  paint("live", "Connected \\u2014 start speaking");
}} else {{
  const client = new RetellWebClient();
  window.__clClient = client;
  window.__clCallId = CALL_ID;
  bind(client);
  paint("connecting", "Requesting microphone\\u2026");
  client.startCall({{ accessToken: TOKEN }}).then(() => {{
    paint("live", "Connected \\u2014 start speaking");
  }}).catch((err) => {{
    paint("error", "Could not start the call");
    const box = $("cl-err");
    if (box) {{
      box.textContent = (err && err.message) ? err.message
        : "The browser blocked the microphone. Allow mic access for this site and try again.";
    }}
  }});
}}
</script>
        """

    try:
        st.html(markup, unsafe_allow_javascript=True)
    except TypeError:
        # Streamlit predates the unsafe_allow_javascript flag. Without it,
        # st.html strips the script silently and the panel would render as a
        # dead placeholder, so say plainly what is wrong instead.
        st.markdown(
            '<div class="cl-note"><b>Streamlit is too old to run the voice call.</b> '
            f"This app needs <code>st.html(..., unsafe_allow_javascript=True)</code>, "
            f"but the running version is <code>{st.__version__}</code>. Upgrade with "
            "<code>pip install -U 'streamlit&gt;=1.61.1'</code>.<br>There is no iframe "
            "fallback: Streamlit's component iframes do not permit microphone access, "
            "so a call started there can never connect.</div>",
            unsafe_allow_html=True,
        )


# --------------------------------------------------------------------------
# Data access
# --------------------------------------------------------------------------
@st.cache_resource(show_spinner=False)
def get_worksheet_client():
    """Authorise gspread once per server process.

    `st.cache_resource` (not `cache_data`) because a live authorised client is
    a connection, not a value — it must not be copied per session, and it is
    not serialisable.
    """
    import gspread
    from google.oauth2.service_account import Credentials

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
    ]
    info = dict(st.secrets["gcp_service_account"])
    creds = Credentials.from_service_account_info(info, scopes=scopes)
    return gspread.authorize(creds)


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def load_claims() -> tuple[pd.DataFrame, str]:
    """Return (claims dataframe, data source label).

    Falls back to the bundled CSV template when Sheets is not wired up yet, so
    `streamlit run streamlit_app.py` produces a working page on a fresh clone
    with no credentials. The page states plainly which source is in use.
    """
    try:
        client = get_worksheet_client()
        sheet_id = st.secrets["sheets"]["spreadsheet_id"]
        tab = st.secrets["sheets"].get("claims_tab", "Claims")
        records = client.open_by_key(sheet_id).worksheet(tab).get_all_records()
        return normalise_claims(pd.DataFrame(records)), "live"
    except Exception:
        try:
            return normalise_claims(pd.read_csv("data/Claims-Template.csv")), "sample"
        except Exception:
            return normalise_claims(pd.DataFrame(columns=CLAIM_COLUMNS)), "empty"


def normalise_claims(df: pd.DataFrame) -> pd.DataFrame:
    """Guarantee the shape the rest of the page assumes.

    Google Sheets happily returns a sheet with missing or reordered columns,
    and a blank row becomes a row of empty strings. Normalising once here
    means no chart has to defend itself.
    """
    for col in CLAIM_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    df = df[CLAIM_COLUMNS].copy()
    for col in CLAIM_COLUMNS:
        df[col] = df[col].astype(str).str.strip()
    df = df[df["claim_id"] != ""]
    df["created_dt"] = pd.to_datetime(df["created_at"], errors="coerce")
    df["urgency"] = df["urgency"].replace("", "Standard")
    df["status"] = df["status"].replace("", "Filed")
    df["incident_type"] = df["incident_type"].replace("", "Other")
    return df


# --------------------------------------------------------------------------
# Charts
# --------------------------------------------------------------------------
def base_layout(fig: go.Figure, height: int = 320) -> go.Figure:
    fig.update_layout(
        height=height,
        margin=dict(l=8, r=8, t=8, b=8),
        paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE,
        font=dict(family=FONT_STACK, size=12, color=INK_SOFT),
        hoverlabel=dict(
            bgcolor="#ffffff",
            bordercolor=AXIS,
            font=dict(family=FONT_STACK, size=12, color=INK),
        ),
        showlegend=False,
    )
    return fig


def chart_by_type(df: pd.DataFrame) -> go.Figure:
    counts = df["incident_type"].value_counts().sort_values(ascending=True)
    fig = go.Figure(
        go.Bar(
            x=counts.values,
            y=counts.index,
            orientation="h",
            # Single series, so a single hue and no legend — the title already
            # says what is being counted. Colouring each bar differently would
            # imply a second variable that does not exist.
            marker=dict(color=SERIES_BLUE, cornerradius=4),
            # Pin bar thickness in category units. Without this, one category
            # stretches into a slab that fills the whole plot area and reads as
            # a coloured rectangle rather than a bar.
            width=0.55,
            text=counts.values,
            textposition="outside",
            textfont=dict(color=INK_SOFT, size=12),
            hovertemplate="<b>%{y}</b><br>%{x} claims<extra></extra>",
        )
    )
    fig.update_xaxes(
        showgrid=True, gridcolor=GRID, gridwidth=1, zeroline=False,
        showline=False, tickfont=dict(color=INK_MUTED), title=None,
        rangemode="tozero",
    )
    fig.update_yaxes(
        showgrid=False, showline=False, tickfont=dict(color=INK_SOFT, size=12), title=None,
    )
    # Grow with the number of categories so bar thickness stays constant
    # instead of the chart stretching whatever bars it has to fill 320px.
    return base_layout(fig, height=max(180, 58 * max(len(counts), 1) + 70))


def chart_urgency(df: pd.DataFrame) -> go.Figure:
    counts = df["urgency"].value_counts()
    order = [u for u in ("Standard", "Urgent") if u in counts.index]
    order += [u for u in counts.index if u not in order]
    values = [int(counts[u]) for u in order]
    # Urgency is a state, not an arbitrary category, so it takes the reserved
    # status colour rather than "series 2" — and every slice carries a text
    # label, so the meaning never rests on colour alone.
    colors = [STATUS_CRITICAL if u == "Urgent" else SERIES_BLUE for u in order]

    fig = go.Figure(
        go.Pie(
            labels=order,
            values=values,
            hole=0.62,
            sort=False,
            direction="clockwise",
            marker=dict(colors=colors, line=dict(color=SURFACE, width=2)),
            textinfo="label+percent",
            textfont=dict(family=FONT_STACK, size=13, color="#ffffff"),
            hovertemplate="<b>%{label}</b><br>%{value} claims (%{percent})<extra></extra>",
        )
    )
    total = sum(values)
    fig.add_annotation(
        text=f"<b style='font-size:26px;color:{INK}'>{total}</b>"
             f"<br><span style='font-size:11px;color:{INK_MUTED}'>CLAIMS</span>",
        showarrow=False, font=dict(family=FONT_STACK),
    )
    return base_layout(fig)


def chart_over_time(df: pd.DataFrame) -> go.Figure:
    dated = df.dropna(subset=["created_dt"])
    if dated.empty:
        return base_layout(go.Figure())

    daily = (
        dated.set_index("created_dt")
        .resample("D")
        .size()
        .rename("claims")
        .reset_index()
    )
    fig = go.Figure(
        go.Scatter(
            x=daily["created_dt"],
            y=daily["claims"],
            mode="lines+markers",
            line=dict(color=SERIES_BLUE, width=2, shape="spline", smoothing=0.4),
            marker=dict(size=8, color=SERIES_BLUE, line=dict(color=SURFACE, width=2)),
            fill="tozeroy",
            fillcolor="rgba(42,120,214,.09)",
            hovertemplate="<b>%{x|%d %b %Y}</b><br>%{y} claims filed<extra></extra>",
        )
    )
    fig.update_xaxes(
        showgrid=False, showline=True, linecolor=AXIS,
        tickfont=dict(color=INK_MUTED), title=None,
    )
    fig.update_yaxes(
        showgrid=True, gridcolor=GRID, zeroline=False, showline=False,
        tickfont=dict(color=INK_MUTED), title=None,
        rangemode="tozero", dtick=1,
    )
    # A crosshair makes a sparse daily series readable — without it you cannot
    # tell which day a point sits on once there are more than a handful.
    fig.update_layout(hovermode="x unified")
    return base_layout(fig)


PLOTLY_CONFIG = {"displayModeBar": False, "responsive": True}


# --------------------------------------------------------------------------
# Page
# --------------------------------------------------------------------------
def main() -> None:
    inject_css()

    st.markdown(
        """
        <div class="cl-hero"><div class="cl-hero-inner">
          <div class="cl-eyebrow"><span class="cl-dot"></span> Live demo · voice agent online</div>
          <h1>Insurance claims, filed and triaged <em>by voice</em>.</h1>
          <p>ClaimLine AI answers policy questions, validates a caller's policy in real time,
             files their claim, triages it for urgency, and reads the claim ID back — in one
             natural conversation, with zero manual data entry on the business side.</p>
          <div class="cl-pills">
            <span class="cl-pill">Retell Conversation Flow</span>
            <span class="cl-pill">n8n · sync + async workflows</span>
            <span class="cl-pill">Google Sheets data layer</span>
            <span class="cl-pill">Keyword-rule urgency triage</span>
          </div>
        </div></div>
        """,
        unsafe_allow_html=True,
    )

    # ---- voice widget ----------------------------------------------------
    section(
        "Talk to it",
        "Call the agent from this page",
        "The widget below is the real production agent, not a recording. Allow microphone "
        "access when your browser asks, then try filing a claim against policy POL-10234.",
    )

    api_key = secret("retell", "api_key")
    agent_id = secret("retell", "agent_id")

    # Validate the SHAPE of the credentials, not merely their presence. A
    # leftover placeholder is a non-empty string, so a truthiness check would
    # happily render a call button that can never connect -- much harder to
    # diagnose than no button at all.
    key_ok = api_key.startswith("key_")
    agent_ok = agent_id.startswith("agent_")

    if not (key_ok and agent_ok):
        problems = []
        if not api_key:
            problems.append("<code>retell.api_key</code> is missing")
        elif not key_ok:
            problems.append(
                "<code>retell.api_key</code> does not start with <code>key_</code> — "
                "it is still a placeholder, or a <i>public</i> key was pasted instead "
                "of the private API key"
            )
        if not agent_id:
            problems.append("<code>retell.agent_id</code> is missing")
        elif not agent_ok:
            problems.append(
                "<code>retell.agent_id</code> does not start with <code>agent_</code>"
            )
        st.markdown(
            '<div class="cl-note"><b>Voice calling not configured.</b><ul style="margin:.5rem 0 .4rem 1rem;">'
            + "".join(f"<li>{p}</li>" for p in problems)
            + "</ul>Set these in <code>.streamlit/secrets.toml</code> locally, or in "
            "<b>Settings → Secrets</b> on Streamlit Community Cloud (editing the local "
            "file does <i>not</i> update the deployed app).</div>",
            unsafe_allow_html=True,
        )
    else:
        call_col, hint_col = st.columns([1, 3])
        with call_col:
            start = st.button("📞  Talk to ClaimLine AI", width="stretch")
        with hint_col:
            st.markdown(
                f'<div style="padding-top:.55rem;font-size:.86rem;color:{INK_MUTED};">'
                "Your browser will ask for microphone access — that is the call "
                "connecting, not a tracker.</div>",
                unsafe_allow_html=True,
            )

        if start:
            # Mint the token at the moment of the click. It is single-use and
            # expires in about ten minutes, so it cannot be prepared in advance.
            try:
                call = create_web_call(api_key, agent_id)
                st.session_state["cl_call"] = {
                    "token": call["access_token"],
                    "call_id": call.get("call_id", ""),
                }
            except Exception as exc:  # noqa: BLE001 - surfaced to the user below
                st.session_state["cl_call"] = None
                st.session_state["cl_call_error"] = str(exc)

        if st.session_state.get("cl_call_error"):
            st.markdown(
                '<div class="cl-note"><b>Could not start a call.</b> Retell rejected the '
                f'request: <code>{st.session_state["cl_call_error"]}</code><br>Check that '
                "<code>retell.api_key</code> is the private API key and that the agent is "
                "published.</div>",
                unsafe_allow_html=True,
            )
            st.session_state["cl_call_error"] = ""

        if st.session_state.get("cl_call"):
            render_voice_call(
                st.session_state["cl_call"]["token"],
                st.session_state["cl_call"]["call_id"],
            )

    st.markdown(
        f"""
        <div class="cl-card" style="margin-top:1.1rem;">
          <div style="font-weight:700;font-size:.95rem;margin-bottom:.7rem;">Try saying</div>
          <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:.7rem;">
            <div style="border-left:3px solid {SERIES_BLUE};padding-left:.75rem;font-size:.9rem;color:{INK_SOFT};">
              “What documents do I need for a home claim?”<br>
              <span style="color:{INK_MUTED};font-size:.8rem;">→ answered from the knowledge base</span>
            </div>
            <div style="border-left:3px solid {SERIES_BLUE};padding-left:.75rem;font-size:.9rem;color:{INK_SOFT};">
              “I need to file a claim. My policy is POL-10234.”<br>
              <span style="color:{INK_MUTED};font-size:.8rem;">→ validates, collects details, files, reads back a claim ID</span>
            </div>
            <div style="border-left:3px solid {STATUS_CRITICAL};padding-left:.75rem;font-size:.9rem;color:{INK_SOFT};">
              “There was a fire and someone was taken to hospital.”<br>
              <span style="color:{INK_MUTED};font-size:.8rem;">→ triaged Urgent, 24–48h review</span>
            </div>
            <div style="border-left:3px solid {SERIES_BLUE};padding-left:.75rem;font-size:.9rem;color:{INK_SOFT};">
              “Can you check the status of claim CLM-000001?”<br>
              <span style="color:{INK_MUTED};font-size:.8rem;">→ looked up live in the sheet</span>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ---- data ------------------------------------------------------------
    df, source = load_claims()

    head_l, head_r = st.columns([5, 1])
    with head_l:
        section(
            "Live operations",
            "Claims dashboard",
            "Reading the same Google Sheet the voice agent writes to. Cached for "
            f"{CACHE_TTL_SECONDS} seconds to stay inside the Sheets API free quota.",
        )
    with head_r:
        st.markdown("<div style='height:3.4rem'></div>", unsafe_allow_html=True)
        if st.button("↻ Refresh data", width="stretch"):
            # Clearing the cache is what actually forces a re-read; the rerun
            # alone would just serve the cached frame again.
            load_claims.clear()
            st.rerun()

    if source == "sample":
        st.markdown(
            '<div class="cl-note"><b>Showing bundled sample data.</b> Google Sheets '
            'credentials are not configured, so the page is rendering '
            '<code>data/Claims-Template.csv</code>. Add the <code>gcp_service_account</code> '
            'and <code>sheets</code> secrets to switch to live data.</div>',
            unsafe_allow_html=True,
        )
    elif source == "empty":
        st.markdown(
            '<div class="cl-note"><b>No claims yet.</b> File one through the voice agent '
            'above and hit Refresh.</div>',
            unsafe_allow_html=True,
        )

    total = len(df)
    urgent = int((df["urgency"].str.lower() == "urgent").sum())
    urgent_pct = f"{(urgent / total * 100):.0f}% of all claims" if total else "—"
    today = datetime.now().date()
    today_count = int((df["created_dt"].dt.date == today).sum()) if total else 0
    top_type = df["incident_type"].mode().iat[0] if total else "—"

    t1, t2, t3, t4 = st.columns(4)
    t1.markdown(tile("Total claims", f"{total:,}", "all time"), unsafe_allow_html=True)
    t2.markdown(
        tile("Urgent", f"{urgent:,}", urgent_pct, critical=urgent > 0),
        unsafe_allow_html=True,
    )
    t3.markdown(tile("Filed today", f"{today_count:,}", today.strftime("%d %b %Y")), unsafe_allow_html=True)
    t4.markdown(tile("Most common", top_type, "incident type"), unsafe_allow_html=True)

    # ---- charts ----------------------------------------------------------
    st.markdown("<div style='height:1.6rem'></div>", unsafe_allow_html=True)

    def chart_block(title: str, subtitle: str, fig: go.Figure) -> None:
        st.markdown(
            f'<div class="cl-chart-head"><div class="t">{title}</div>'
            f'<div class="s">{subtitle}</div></div>',
            unsafe_allow_html=True,
        )
        st.plotly_chart(fig, width="stretch", config=PLOTLY_CONFIG)

    c1, c2 = st.columns([3, 2])
    with c1:
        chart_block("Claims by incident type",
                    "Where the claim volume actually comes from",
                    chart_by_type(df))
    with c2:
        chart_block("Urgency split",
                    "Urgent claims are reviewed in 24–48h",
                    chart_urgency(df))

    st.markdown("<div style='height:1.2rem'></div>", unsafe_allow_html=True)
    chart_block("Claims filed over time",
                "Daily volume, by the timestamp the agent wrote",
                chart_over_time(df))

    # ---- table + lookup --------------------------------------------------
    section(
        "Records",
        "Claim register & lookup",
        "The full claims table, plus the same claim-ID lookup the voice agent performs — "
        "read-only here.",
    )

    tab_table, tab_lookup = st.tabs(["  All claims  ", "  Look up a claim  "])

    with tab_table:
        if df.empty:
            st.info("No claims to show yet.")
        else:
            display = df.drop(columns=["created_dt"]).sort_values(
                "created_at", ascending=False
            )
            st.dataframe(
                display,
                width="stretch",
                hide_index=True,
                column_config={
                    "claim_id": st.column_config.TextColumn("Claim ID", width="small"),
                    "policy_number": st.column_config.TextColumn("Policy", width="small"),
                    "holder_name": st.column_config.TextColumn("Policyholder"),
                    "incident_type": st.column_config.TextColumn("Type", width="small"),
                    "incident_date": st.column_config.TextColumn("Incident date", width="small"),
                    "description": st.column_config.TextColumn("Description", width="large"),
                    "urgency": st.column_config.TextColumn("Urgency", width="small"),
                    "status": st.column_config.TextColumn("Status", width="small"),
                    "email": st.column_config.TextColumn("Email"),
                    "created_at": st.column_config.TextColumn("Filed at", width="small"),
                },
            )
            st.caption(f"{len(display)} claim(s) · refreshed {datetime.now():%H:%M:%S}")

    with tab_lookup:
        query = st.text_input(
            "Claim ID",
            placeholder="e.g. CLM-000001",
            label_visibility="collapsed",
        )
        if query:
            # Match the same forgiving normalisation n8n applies, so "42",
            # "clm 42" and "CLM-000042" all find the same record.
            digits = "".join(ch for ch in query if ch.isdigit())
            wanted = f"CLM-{digits.zfill(6)}" if digits else query.strip().upper()
            hit = df[df["claim_id"].str.upper() == wanted]

            if hit.empty:
                st.markdown(
                    f'<div class="cl-note">No claim found matching '
                    f'<b>{wanted}</b>. Check the ID and try again.</div>',
                    unsafe_allow_html=True,
                )
            else:
                r = hit.iloc[0]
                is_urgent = str(r["urgency"]).lower() == "urgent"
                badge_cls = "urgent" if is_urgent else "standard"
                sla = (
                    "Priority review within 24–48 hours"
                    if is_urgent
                    else "Review within 5–7 business days"
                )
                st.markdown(
                    f"""
                    <div class="cl-card">
                      <div style="display:flex;justify-content:space-between;align-items:center;
                                  margin-bottom:.9rem;">
                        <div style="font-size:1.3rem;font-weight:800;letter-spacing:-.02em;">
                          {r['claim_id']}</div>
                        <span class="cl-badge {badge_cls}">{r['urgency']}</span>
                      </div>
                      <div class="cl-kv"><span>Status</span><span>{r['status']}</span></div>
                      <div class="cl-kv"><span>Policyholder</span><span>{r['holder_name']}</span></div>
                      <div class="cl-kv"><span>Policy</span><span>{r['policy_number']}</span></div>
                      <div class="cl-kv"><span>Incident type</span><span>{r['incident_type']}</span></div>
                      <div class="cl-kv"><span>Incident date</span><span>{r['incident_date']}</span></div>
                      <div class="cl-kv"><span>Filed at</span><span>{r['created_at']}</span></div>
                      <div class="cl-kv"><span>Description</span><span>{r['description']}</span></div>
                      <div style="margin-top:.9rem;font-size:.86rem;color:{INK_SOFT};">{sla}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

    # ---- footer ----------------------------------------------------------
    st.markdown(
        """
        <div class="cl-footer">
          <b>Demonstration project — no real data.</b> ClaimLine Insurance is fictional.
          Every policy, claim, name and email address shown here is seeded demo data
          created for a portfolio build. Do not enter real personal, medical or
          insurance information into the voice agent.
          <br><br>
          Built by <b>Muhammad Ali Hashim</b> ·
          <a href="https://github.com/alihashim786" target="_blank">GitHub</a> ·
          <a href="https://linkedin.com/in/alihashimraza" target="_blank">LinkedIn</a>
        </div>
        """,
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
