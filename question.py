import os
import datetime
import random
import requests
import streamlit as st

# ==========================================
# 0. PAGE CONFIG & CENTERED COLLEGE LOGO
# ==========================================
st.set_page_config(
    page_title="Academic Assessment Portal",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded"
)

with st.sidebar:
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        if os.path.exists("pjc_logo.jpg"):
            st.image("pjc_logo.jpg", width=120)
    st.title("Portal")

# ==========================================
# 1. SUPABASE CLOUD STORAGE BACKEND
# ==========================================
class SupabaseBackend:
    name = "Supabase"
    persistent = True
    TABLE = "documents"
    BUCKET = "portal-files"

    def __init__(self, url, key):
        self.url = url.rstrip("/")
        self.s = requests.Session()
        self.s.headers.update({
            "apikey": key,
            "Authorization": f"Bearer {key}"
        })

    def _req(self, method, endpoint, params=None, json_data=None):
        headers = {}
        if json_data is not None:
            headers["Content-Type"] = "application/json"
            headers["Prefer"] = "resolution=merge-duplicates"
        
        url = f"{self.url}{endpoint}"
        r = self.s.request(method, url, params=params, json=json_data, headers=headers)
        if r.status_code >= 400:
            raise Exception(f"Supabase error {r.status_code}: {r.text[:300]}")
        return r.json() if r.content else None

    def get(self, key, default=None):
        try:
            rows = self._req("GET", f"/rest/v1/{self.TABLE}", params={"path": f"eq.{key}"})
            if rows and isinstance(rows, list):
                return rows[0].get("data", default)
        except Exception:
            pass
        return default

    def set(self, key, data):
        payload = {
            "path": key,
            "data": data,
            "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
        }
        self._req("POST", f"/rest/v1/{self.TABLE}", json_data=payload)

@st.cache_resource
def _make_backend():
    url = st.secrets.get("SUPABASE_URL", os.environ.get("SUPABASE_URL", ""))
    key = st.secrets.get("SUPABASE_SERVICE_KEY", os.environ.get("SUPABASE_SERVICE_KEY", ""))
    if url and key:
        try:
            b = SupabaseBackend(url, key)
            b.get("ping", {})
            return b
        except Exception:
            pass
    return None

backend = _make_backend()

def doc_get(key, default=None):
    if backend:
        return backend.get(key, default)
    return default

def doc_set(key, data):
    if backend:
        backend.set(key, data)

# ==========================================
# 2. PHASE 1: MULTI-TEST DATABASE HELPERS
# ==========================================
def get_department_tests(dept_code):
    key = f"tests/{dept_code}"
    return doc_get(key, {})

def save_department_test(dept_code, test_id, test_data):
    key = f"tests/{dept_code}"
    tests = get_department_tests(dept_code)
    tests[test_id] = test_data
    doc_set(key, tests)

def get_test_questions(dept_code, test_id):
    key = f"bank/{dept_code}/{test_id}"
    questions = doc_get(key, [])
    if not questions:
        questions = doc_get(f"bank/{dept_code}", [])
    return questions

def save_test_questions(dept_code, test_id, questions):
    key = f"bank/{dept_code}/{test_id}"
    doc_set(key, questions)
# ==========================================
# 3. TEACHER TEST MANAGER VIEW
# ==========================================
def render_teacher_test_manager(dept_code):
    st.subheader(f"📋 Manage Examinations — Department: {dept_code.upper()}")
    
    tests = get_department_tests(dept_code)
    
    with st.expander("➕ Create New Test / Examination", expanded=not bool(tests)):
        with st.form("create_test_form"):
            test_title = st.text_input("Test Title (e.g., Unit Test 1, Internal Assessment)")
            col1, col2 = st.columns(2)
            with col1:
                open_date = st.date_input("Opening Date")
                open_time = st.time_input("Opening Time")
            with col2:
                close_date = st.date_input("Closing Date")
                close_time = st.time_input("Closing Time")
                
            duration_mins = st.number_input("Time Limit (Minutes)", min_value=5, max_value=300, value=45)
            
            st.markdown("**Security & Randomization Options**")
            shuffle_q = st.checkbox("Shuffle Question Order for Students", value=True)
            shuffle_opts = st.checkbox("Shuffle MCQ Options", value=True)
            published = st.checkbox("Publish Immediately (Visible to Students)", value=False)
            
            submitted = st.form_submit_button("Create Test")
            if submitted and test_title:
                open_dt = datetime.datetime.combine(open_date, open_time)
                close_dt = datetime.datetime.combine(close_date, close_time)
                
                if open_dt >= close_dt:
                    st.error("Error: Closing time must be after opening time.")
                else:
                    test_id = f"test_{int(datetime.datetime.now().timestamp())}"
                    test_meta = {
                        "test_id": test_id,
                        "title": test_title,
                        "open_at": open_dt.isoformat(),
                        "close_at": close_dt.isoformat(),
                        "duration_mins": int(duration_mins),
                        "shuffle_q": shuffle_q,
                        "shuffle_opts": shuffle_opts,
                        "published": published
                    }
                    save_department_test(dept_code, test_id, test_meta)
                    st.success(f"Successfully created test: {test_title}!")
                    st.rerun()

    # List Existing Tests
    if tests:
        st.markdown("### Existing Department Tests")
        for tid, tdata in tests.items():
            with st.container():
                status_badge = "🟢 Published" if tdata.get('published', False) else "🔴 Draft"
                st.markdown(f"**{tdata['title']}** | ID: `{tid}` | Status: {status_badge}")
                st.caption(f"Opens: {tdata['open_at']} | Closes: {tdata['close_at']} | Duration: {tdata['duration_mins']} mins")
                
                col_m1, col_m2 = st.columns(2)
                with col_m1:
                    if st.button("Manage Questions", key=f"manage_q_{tid}"):
                        st.session_state["active_managing_test"] = tid
                with col_m2:
                    new_pub_state = not tdata.get("published", False)
                    if st.button("Toggle Publish", key=f"toggle_pub_{tid}"):
                        tdata["published"] = new_pub_state
                        save_department_test(dept_code, tid, tdata)
                        st.rerun()
                st.divider()

# ==========================================
# 4. STUDENT TIMED EXAM PORTAL
# ==========================================
def render_student_exam_portal(dept_code, student_id="student_guest"):
    st.subheader(f"📝 Timed Examinations — {dept_code.upper()}")
    
    tests = get_department_tests(dept_code)
    published_tests = {tid: t for tid, t in tests.items() if t.get("published", False)}
    
    if not published_tests:
        st.info("No active examinations are currently published for this department.")
        return
        
    selected_test_id = st.selectbox(
        "Select Test to Take", 
        options=list(published_tests.keys()), 
        format_func=lambda x: published_tests[x]["title"]
    )
    test_info = published_tests[selected_test_id]
    
    now = datetime.datetime.now()
    open_at = datetime.datetime.fromisoformat(test_info["open_at"])
    close_at = datetime.datetime.fromisoformat(test_info["close_at"])
    
    # Time Window Enforcement
    if now < open_at:
        st.warning(f"⏳ This test is locked. It will open at **{open_at.strftime('%Y-%m-%d %H:%M')}**.")
        return
    if now > close_at:
        st.error("🔒 This test has closed and is no longer accepting submissions.")
        return
        
    st.markdown(f"### ⏱️ {test_info['title']}")
    st.info(f"Time Limit: **{test_info['duration_mins']} minutes**. Once started, responses are securely recorded.")
    
    if st.button("🚀 Start Exam Now"):
        st.session_state[f"exam_started_{selected_test_id}"] = True
        st.session_state[f"exam_start_time_{selected_test_id}"] = datetime.datetime.now().isoformat()
        st.rerun()
        
    if st.session_state.get(f"exam_started_{selected_test_id}", False):
        questions = get_test_questions(dept_code, selected_test_id)
        if not questions:
            st.warning("No questions have been added to this test bank yet.")
            return
            
        # Deterministic Shuffling per Student & Test
        if test_info.get("shuffle_q", True):
            rng = random.Random(f"{selected_test_id}_{student_id}")
            rng.shuffle(questions)
            
        with st.form(f"exam_form_{selected_test_id}"):
            answers = {}
            for idx, q in enumerate(questions):
                st.markdown(f"**Q{idx+1}: {q.get('question_text', '')}**")
                options = q.get("options", [])
                
                if test_info.get("shuffle_opts", True) and options:
                    opt_rng = random.Random(f"{selected_test_id}_{student_id}_q{idx}")
                    opt_rng.shuffle(options)
                    
                answers[idx] = st.radio(f"Select answer for Q{idx+1}", options, key=f"ans_{selected_test_id}_{idx}")
                st.divider()
                
            submitted = st.form_submit_button("📥 Submit Examination")
            if submitted:
                sub_key = f"submissions/{dept_code}/{selected_test_id}/{student_id}"
                doc_set(sub_key, {
                    "answers": answers, 
                    "submitted_at": datetime.datetime.now().isoformat(),
                    "student_id": student_id
                })
                st.success("Exam submitted successfully! Your responses have been saved.")
                st.session_state[f"exam_started_{selected_test_id}"] = False

# ==========================================
# 5. MAIN APPLICATION ENTRYPOINT & ROUTING
# ==========================================
def main():
    st.sidebar.markdown("---")
    menu = st.sidebar.radio("Navigation", ["Home", "Timed Exams", "Teacher Test Manager", "Study Materials", "Admin Console"])
    
    dept_code = st.sidebar.selectbox("Select Department", ["physics", "bengali", "chemistry", "mathematics"])
    
    if menu == "Home":
        st.title("🎓 Prabhu Jagatbandhu College Assessment Portal")
        if backend:
            st.success("🟢 Storage Backend: Supabase (Persistent Cloud Storage)")
        else:
            st.warning("⚠️ Storage Backend: Local Disk (Configure Supabase Secrets)")
        st.info("Use the sidebar to navigate between timed examinations, test management, and study resources.")
        
    elif menu == "Timed Exams":
        render_student_exam_portal(dept_code, student_id="student_demo")
        
    elif menu == "Teacher Test Manager":
        render_teacher_test_manager(dept_code)
        
    elif menu == "Study Materials":
        st.subheader(f"📚 Department Study Materials — {dept_code.upper()}")
        st.write("Upload and browse departmental syllabi and notes here.")
        
    elif menu == "Admin Console":
        st.subheader("⚙️ Administrator Console")
        st.write("Manage faculty accounts, audit logs, and Supabase storage connection status.")

if __name__ == "__main__":
    main()
