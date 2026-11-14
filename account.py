"""Password change + sign-out for the logged-in teacher/admin."""
import streamlit as st

from .. import auth
from ..ui import STRETCH, banner, goto, P_HOME
from ..i18n import tr, trf


def render(user):
    banner(tr("⚙️ My Account"), trf("Signed in as **{0}** · role: {1}", user['username'], user['role']))
    if "pw_ok" in st.session_state:
        st.success(tr(st.session_state.pop("pw_ok")))
    if user.get("must_change"):
        st.warning(tr("You are using a temporary password. Set a new one to unlock the dashboards."))
    with st.form("pw_form", clear_on_submit=True):
        old = st.text_input(tr("Current password"), type="password")
        new = st.text_input(trf("New password (min {0} chars, letters + digits)", auth.config.MIN_PASSWORD_LEN), type="password")
        new2 = st.text_input(tr("Repeat new password"), type="password")
        go = st.form_submit_button(tr("🔑 Change Password"), **STRETCH)
    if go:
        if new != new2:
            st.error(tr("The new passwords do not match."))
        else:
            err = auth.change_password(user, old, new)
            if err:
                st.error(tr(err))
            else:
                st.session_state["pw_ok"] = "✅ Password updated. Use the NEW password the next time you sign in."
                st.rerun()
    st.markdown("---")
    if st.button(tr("🚪 Sign Out"), **STRETCH):
        auth.logout()
        goto(P_HOME)
        st.rerun()
