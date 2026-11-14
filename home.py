"""Landing page: department selection."""
import streamlit as st

from .. import config
from ..ui import render_hero, STRETCH, goto, P_TAKE
from ..auth import current_user
from ..i18n import tr, trf, dname, lang


def _enter():
    choice = st.session_state.get(f"dept_choice_{lang()}")
    if choice != st.session_state.get("dept"):
        for k in ("stu_step", "stu_draft", "stu_primed", "stu_result"):
            st.session_state.pop(k, None)
    st.session_state["dept"] = choice
    goto(P_TAKE)


def render():
    render_hero(320)
    st.title(tr("🎓 Departmental Assessment & Grading Portal"))
    st.markdown(f"**{tr(config.INSTITUTION_NAME)}**")
    st.caption(tr(config.INSTITUTION_ADDRESS))
    st.caption(tr("Use the menu on the left (☰ on phones) to switch language."))
    st.markdown("---")

    st.markdown(tr("<div class='dept-card'><h3 style='margin:0'>🏛️ Select Your Department</h3>"
                "<div style='margin-top:6px'>Pick the department whose assessments and resources you need.</div></div>"),
                unsafe_allow_html=True)
    current = st.session_state.get("dept")
    idx = config.DEPARTMENTS.index(current) if current in config.DEPARTMENTS else None
    st.selectbox(
        tr("Choose the academic department whose resources you want to access"),
        config.DEPARTMENTS, index=idx, placeholder=tr("Select a department…"), key=f"dept_choice_{lang()}", format_func=dname,
    )

    chosen = st.session_state.get(f"dept_choice_{lang()}")
    st.button(tr("🚀 Enter Student Portal"), type="primary", disabled=not chosen,
              on_click=_enter, **STRETCH)

    c1, c2, c3 = st.columns(3)
    c1.markdown(tr("##### 🎓 Students\nTake assessments, review and edit answers, then download your report card."))
    c2.markdown(tr("##### 👨‍🏫 Faculty\nSign in from the sidebar to create questions, evaluate and view analytics."))
    c3.markdown(tr("##### 🛡️ Administrators\nManage departmental faculty credentials and monitor all departments."))
    if current_user() is None:
        st.info(tr("🔐 Faculty and administrators: open **Faculty Login** from the sidebar. "
                "Teacher pages are never shown to students."))
