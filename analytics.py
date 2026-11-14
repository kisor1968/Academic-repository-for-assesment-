"""Performance analytics dashboard (finalised evaluations only)."""
import pandas as pd
import streamlit as st

from .. import config
from ..grading import totals
from ..storage import DeptStore
from ..ui import banner, show_df
from ..i18n import tr, trf, dname

GRADES = [g for _, g, _ in config.GRADE_SCALE]


def _results_frame(subs):
    rows = []
    for s in subs:
        if s["status"] != "finalized":
            continue
        t = totals(s)
        rows.append({
            "Submission": s["submission_id"], "Roll": s["roll_no"], "Student": s["student_name"],
            "Marks": t["obtained"], "Max": t["max"], "Percent": t["percent"], "Grade": t["grade"],
            "Result": "PASS" if t["passed"] else "FAIL", "Date": s["timestamp"][:10],
        })
    return pd.DataFrame(rows)


def _question_frame(subs):
    rows = []
    for s in subs:
        if s["status"] != "finalized":
            continue
        for q in s["paper"]:
            got = min(float(s["marks"].get(str(q["id"]), 0) or 0), float(q["max_marks"]))
            rows.append({"Q": f"Q{q['number']}", "Type": q["type"], "pct": got / float(q["max_marks"]) * 100})
    return pd.DataFrame(rows)


def _kpis(df, total_subs):
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric(tr("Submissions"), total_subs)
    c2.metric(tr("Evaluated"), len(df))
    c3.metric(tr("Average"), f"{df['Percent'].mean():.1f}%")
    c4.metric(tr("Highest"), f"{df['Percent'].max():.1f}%")
    c5.metric(tr("Pass rate"), f"{(df['Result'] == 'PASS').mean() * 100:.0f}%")


def _department_view(store):
    subs = store.submissions()
    if not subs:
        st.info(tr("No submissions in this department yet."))
        return
    df = _results_frame(subs)
    st.markdown(tr("##### 🧭 Evaluation progress"))
    done = len(df)
    st.progress(done / len(subs), text=trf("{0} of {1} submissions finalised", done, len(subs)))
    if df.empty:
        st.info(tr("Analytics appear once at least one evaluation is finalised."))
        return
    _kpis(df, len(subs))

    t_dist, t_q, t_students = st.tabs([tr("📈 Score Distribution"), tr("🧩 Question Analysis"), tr("🏅 Student Records")])
    with t_dist:
        bins = list(range(0, 101, 10))
        labels = [f"{b}-{b + 10}" for b in bins[:-1]]
        hist = pd.cut(df["Percent"], bins=bins, labels=labels, include_lowest=True, right=False)
        hist = hist.fillna(labels[-1]).value_counts().reindex(labels, fill_value=0)
        st.markdown(tr("**Score distribution (% bands)**"))
        st.bar_chart(hist, color="#ff2e97")
        c1, c2 = st.columns(2)
        with c1:
            st.markdown(tr("**Grade distribution**"))
            st.bar_chart(df["Grade"].value_counts().reindex(GRADES, fill_value=0), color="#00e5ff")
        with c2:
            st.markdown(tr("**Submissions per day**"))
            st.line_chart(pd.to_datetime(df["Date"]).value_counts().sort_index(), color="#ffd400")
        st.caption(trf("Median {0:.1f}% · Std. deviation {1:.1f} · Lowest {2:.1f}%", df['Percent'].median(), df['Percent'].std(ddof=0), df['Percent'].min()))
    with t_q:
        qdf = _question_frame(subs)
        avg = qdf.groupby("Q", sort=False)["pct"].mean().round(1)
        st.markdown(tr("**Average score per question (%)** — low bars flag difficult or poorly-taught topics"))
        st.bar_chart(avg, color="#7b2ff7")
        weak = avg[avg < 50]
        if len(weak):
            st.warning("Questions averaging below 50%: " + ", ".join(f"{q} ({v:.0f}%)" for q, v in weak.items()))
        by_type = qdf.groupby("Type")["pct"].mean().round(1)
        st.markdown(tr("**Average by question type (%)**"))
        st.bar_chart(by_type, color="#00ff9d")
    with t_students:
        c1, c2 = st.columns(2)
        c1.markdown(tr("**🏆 Top performers**"))
        show_df(df.nlargest(5, "Percent")[["Roll", "Student", "Percent", "Grade"]], c1)
        c2.markdown(tr("**🚨 Needs attention (below pass mark)**"))
        low = df[df["Percent"] < config.PASS_PERCENT].sort_values("Percent")[["Roll", "Student", "Percent", "Grade"]]
        show_df(low, c2) if len(low) else c2.success(tr("Everyone has passed 🎉"))
        st.markdown(tr("**All finalised results**"))
        show_df(df.sort_values("Percent", ascending=False))
        st.download_button(tr("📥 Download results (CSV)"), df.to_csv(index=False).encode("utf-8-sig"),
                           file_name=f"{store.slug}_results.csv", mime="text/csv")


def _all_departments_view():
    rows = []
    for dept in config.DEPARTMENTS:
        subs = DeptStore(dept).submissions()
        df = _results_frame(subs)
        rows.append({
            "Department": dept, "Submissions": len(subs), "Finalised": len(df),
            "Progress %": round(len(df) / len(subs) * 100) if subs else 0,
            "Avg %": round(df["Percent"].mean(), 1) if len(df) else None,
            "Pass rate %": round((df["Result"] == "PASS").mean() * 100) if len(df) else None,
        })
    summary = pd.DataFrame(rows)
    st.markdown(tr("**Departmental progress summary**"))
    show_df(summary)
    if summary["Avg %"].notna().any():
        st.markdown(tr("**Average score by department (%)**"))
        st.bar_chart(summary.set_index("Department")["Avg %"].dropna(), color="#ff2e97")
        st.markdown(tr("**Evaluation progress by department (%)**"))
        st.bar_chart(summary.set_index("Department")["Progress %"], color="#00e5ff")


def render(store, user):
    banner(tr("📊 Performance Analytics"), tr("Scores, distributions and progress — restricted to faculty"))
    if user["role"] == "admin":
        t1, t2 = st.tabs([f"🏛️ {dname(store.dept)}", tr("🌐 All Departments")])
        with t1:
            _department_view(store)
        with t2:
            _all_departments_view()
    else:
        _department_view(store)
