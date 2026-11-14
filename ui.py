"""Shared UI helpers: theme injection, hero banner, section banners, width kwargs."""
import inspect

import streamlit as st
import streamlit.components.v1 as components

from .i18n import tr, lang

from .theme import NEON_CSS, EXTRA_CSS, THREE_HERO

# Streamlit renamed use_container_width -> width="stretch"; support both.
STRETCH = (
    {"width": "stretch"}
    if "width" in inspect.signature(st.button).parameters
    else {"use_container_width": True}
)


def apply_theme():
    # NEON_CSS already contains the cubes; EXTRA_CSS adds v2 widgets.
    st.markdown(NEON_CSS, unsafe_allow_html=True)
    st.markdown(EXTRA_CSS, unsafe_allow_html=True)
    if lang() == "bn":  # letter-spacing breaks Bengali conjuncts
        st.markdown("<style>h1,h2,h3,h4,h5,.stTabs [data-baseweb='tab']{letter-spacing:0 !important;}</style>", unsafe_allow_html=True)


def render_hero(height=320):
    """Three.js banner. Uses st.iframe on new Streamlit, components.html on older versions."""
    html = ("<style>html,body{margin:0;height:100%;background:transparent;overflow:hidden}</style>"
            + THREE_HERO.replace("MOVE YOUR MOUSE · EXPLORE THE BRIDGE", tr("MOVE YOUR MOUSE · EXPLORE THE BRIDGE"))
            .replace("letter-spacing:4px", "letter-spacing:0" if lang() == "bn" else "letter-spacing:4px"))
    if hasattr(st, "iframe"):
        st.iframe(html, height=height)
    else:
        components.html(html, height=height)


def banner(title, subtitle=""):
    st.markdown(
        f"""
        <div style="padding:18px 22px;border-radius:20px;margin-bottom:10px;
             background:linear-gradient(120deg,rgba(255,46,151,.35),rgba(123,47,247,.35),rgba(0,229,255,.3));
             border:1px solid rgba(255,255,255,.25);box-shadow:0 14px 40px rgba(123,47,247,.45);
             transform:perspective(900px) rotateX(4deg);">
          <div style="font-family:Orbitron,sans-serif;font-size:1.5rem;font-weight:800;color:#fff;
               text-shadow:0 0 18px #ff2e97;">{title}</div>
          <div style="color:#d6f6ff;margin-top:4px;">{subtitle}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ---- page names (used for navigation + RBAC) ----
P_HOME = "🏠 Home"
P_TAKE = "📝 Take Assessment"
P_CARD = "🎓 My Report Card"
P_LOGIN = "🔐 Faculty Login"
P_MATERIALS = "📚 Study Materials"
P_UPLOAD = "📤 Upload Materials"
P_CREATOR = "✍️ Question Creator"
P_EVAL = "👨‍🏫 Evaluation"
P_ANALYTICS = "📊 Analytics"
P_ADMIN = "🛡️ Admin Console"
P_ACCOUNT = "⚙️ Account"

TEACHER_PAGES = {P_CREATOR, P_UPLOAD, P_EVAL, P_ANALYTICS}   # teacher/admin only
ADMIN_PAGES = {P_ADMIN}                             # admin only


def goto(page):
    """Request navigation on the next run (safe to call after the sidebar radio exists)."""
    st.session_state["_goto"] = page


def show_df(df, container=None):
    """Table with translated column headers (and PASS/FAIL, question-type values)."""
    d = df.rename(columns=lambda c: tr(c))
    for col in d.columns:
        if d[col].dtype == object:
            d[col] = d[col].map(lambda v: tr(v) if v in ("PASS", "FAIL", "MCQ", "SHORT", "LONG", "CODE") else v)
    (container or st).dataframe(d, hide_index=True)
