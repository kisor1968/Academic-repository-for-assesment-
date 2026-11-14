"""Faculty / administrator sign-in."""
import streamlit as st

from .. import auth
from ..ui import STRETCH, banner, goto, P_CREATOR, P_ACCOUNT, P_ADMIN
from ..i18n import tr, trf


def render(dept):
    banner(tr("🔐 Faculty Sign-In"), tr("Department-scoped credentials issued by the administrator"))
    if dept:
        st.markdown(trf("Signing in to: **{0}**", dept))
    else:
        st.warning(tr("Select your department on the **Home** page first (administrators may sign in directly)."))
    with st.form("login_form", clear_on_submit=False):
        username = st.text_input(tr("Username"), autocomplete="username")
        password = st.text_input(tr("Password"), type="password", autocomplete="current-password")
        go = st.form_submit_button(tr("🔓 Sign In"), **STRETCH)
    if go:
        ok, msg = auth.login(username, password, dept)
        if ok:
            user = st.session_state["auth"]
            if user["must_change"]:
                st.session_state["flash"] = "🔑 Please set a new password to continue."
                goto(P_ACCOUNT)
            else:
                goto(P_ADMIN if user["role"] == "admin" else P_CREATOR)
            st.rerun()
        else:
            st.error(tr(msg))
    st.caption(tr("After 5 failed attempts the account is locked for 5 minutes. Sessions expire after 30 idle minutes."))
