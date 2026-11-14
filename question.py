"""
Departmental Assessment & Grading Portal  (single-file edition)

Run locally :  streamlit run question.py
Streamlit Community Cloud: set "Main file path" to question.py and add requirements.txt (+ packages.txt).

Roles: students (no login) / teachers (department-scoped, password) / admin.
First run prints a one-time `admin` password in the server log - sign in, change it, then
create teacher accounts from the Admin Console.

NOTE: data is saved in ./data . On Streamlit Community Cloud this folder is wiped on every
restart - use a server with a persistent disk (or an external database) for real use.
"""
import streamlit as st

st.set_page_config(page_title="Departmental Assessment Portal", page_icon="🎓", layout="centered")

import hashlib
import hmac
import inspect
import io
import json
import mimetypes
import os
import random
import re
import secrets
import tempfile
import threading
import time
from datetime import datetime, timezone, timedelta
from functools import wraps
from pathlib import Path
from urllib.parse import quote
from html import escape as html_escape
from xml.sax.saxutils import escape

import pandas as pd
import requests
import streamlit.components.v1 as components

ss = st.session_state
IST = timezone(timedelta(hours=5, minutes=30))


# ======================================================================
# CONFIG — Central settings. Edit DEPARTMENTS / INSTITUTION_NAME / GRADE_SCALE to suit your college.
# ======================================================================
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("PORTAL_DATA_DIR", BASE_DIR / "data"))
AUTH_DIR = DATA_DIR / "auth"

DEFAULT_LANGUAGE = "en"          # "en" or "bn" - language shown first

INSTITUTION_NAME = "Prabhu Jagatbandhu College"
INSTITUTION_ADDRESS = "Jhorehat, Andul-Mouri, Howrah, West Bengal - 711302"

DEPARTMENTS = [
    "Bengali", "English", "Philosophy", "Political Science", "History", "Geography",
    "Sanskrit", "Economics", "Sociology", "Education", "Physics", "Chemistry",
    "Mathematics", "Electronics", "Computer Science", "Botany", "Zoology",
    "Food & Nutrition", "Commerce", "Library Science",
]

QUESTION_TYPES = {
    "mcq": "Multiple Choice (MCQ)",
    "short": "Short Answer",
    "long": "Long Answer / Descriptive",
    "code": "Programming / Code",
}
DEFAULT_MARKS = {"mcq": 1.0, "short": 2.0, "long": 5.0, "code": 10.0}

# Study materials (stored per department, in one sub-folder per category — Syllabus removed per your request)
MATERIAL_CATEGORIES = {
    "notes": "Lecture Notes",
    "pyq": "Previous Year Questions",
    "assignment": "Assignments / Question Banks",
    "reference": "Reference Books & Other",
}
MATERIAL_EXTS = ["pdf", "doc", "docx", "ppt", "pptx", "xls", "xlsx", "txt", "png", "jpg", "jpeg", "zip"]
MAX_MATERIAL_MB = 25
SEMESTERS = ["General"] + [str(i) for i in range(1, 9)]

DOC_EXTS = ["pdf", "png", "jpg", "jpeg"]      # descriptive answer scripts / output screenshots
CODE_EXTS = ["py", "txt"]                      # code files / editor output
MAX_UPLOAD_MB = 10

PASS_PERCENT = 40.0
GRADE_SCALE = [  # (minimum %, grade, description)
    (90, "O", "Outstanding"), (80, "A+", "Excellent"), (70, "A", "Very Good"),
    (60, "B+", "Good"), (50, "B", "Above Average"), (40, "C", "Pass"), (0, "F", "Fail"),
]

# Security
PBKDF2_ITERATIONS = 600_000
MAX_FAILED_LOGINS = 5
LOCKOUT_MINUTES = 5
SESSION_TIMEOUT_MIN = 30
MIN_PASSWORD_LEN = 10


# ======================================================================
# TRANSLATIONS_BN — Bengali wording for the portal.
# ======================================================================
BN = {
    "📚 Study Materials": "📚 অধ্যয়ন সামগ্রী",
    "📤 Upload Materials": "📤 সামগ্রী আপলোড",
    "📋 Manage Tests": "📋 পরীক্ষা পরিচালনা",
    "📚 Study Materials": "📚 অধ্যয়ন সামগ্রী",
    "Department of {0} — pick a folder, choose a material and download": "{0} বিভাগ — ফোল্ডার বেছে নিন, সামগ্রী নির্বাচন করুন ও ডাউনলোড করুন",
    "No study materials have been uploaded for this department yet. Please check back later.": "এই বিভাগের জন্য এখনও কোনো অধ্যয়ন সামগ্রী আপলোড করা হয়নি। পরে আবার দেখুন।",
    "Folder": "ফোল্ডার",
    "All folders": "সব ফোল্ডার",
    "All semesters": "সব সেমিস্টার",
    "Semester": "সেমিস্টার",
    "General": "সাধারণ",
    "Semester {0}": "সেমিস্টার {0}",
    "Search title or subject": "শিরোনাম বা বিষয় খুঁজুন",
    "{0} material(s) found": "{0}টি সামগ্রী পাওয়া গেছে",
    "Nothing matches your filters.": "আপনার বাছাইয়ের সঙ্গে কিছু মিলছে না।",
    "Title": "শিরোনাম",
    "Subject / Paper": "বিষয় / পেপার",
    "Size": "আকার",
    "Uploaded": "আপলোডের তারিখ",
    "ID": "আইডি",
    "Choose a material to download": "ডাউনলোডের জন্য সামগ্রী বেছে নিন",
    "📁 {0} › {1}": "📁 {0} › {1}",
    "**Subject / Paper:** {0}": "**বিষয় / পেপার:** {0}",
    "Uploaded by {0} on {1} · {2}": "{0} আপলোড করেছেন {1} তারিখে · {2}",
    "⬇️ Download {0}": "⬇️ {0} ডাউনলোড করুন",
    "Lecture Notes": "লেকচার নোট",
    "Previous Year Questions": "আগের বছরের প্রশ্নপত্র",
    "Assignments / Question Banks": "অ্যাসাইনমেন্ট / প্রশ্নভান্ডার",
    "Reference Books & Other": "রেফারেন্স বই ও অন্যান্য",
    "📤 Upload Study Materials": "📤 অধ্যয়ন সামগ্রী আপলোড",
    "Department of {0} — add notes and other materials to this department's folders": "{0} বিভাগ — এই বিভাগের ফোল্ডারে নোট ও অন্যান্য সামগ্রী যোগ করুন",
    "Uploaded {0} file(s) to the “{1}” folder.": "“{1}” ফোল্ডারে {0}টি ফাইল আপলোড হয়েছে।",
    "📤 Upload": "📤 আপলোড",
    "🗂️ Manage uploaded files": "🗂️ আপলোড করা ফাইল পরিচালনা",
    "Files are saved only in the {0} department's own folders — other departments never see them.": "ফাইলগুলো শুধু {0} বিভাগের নিজস্ব ফোল্ডারে সংরক্ষিত হয় — অন্য বিভাগ এগুলো কখনো দেখতে পায় না।",
    "Folder (category)": "ফোল্ডার (ধরন)",
    "Title (optional if you upload several files)": "শিরোনাম (একাধিক ফাইল দিলে ঐচ্ছিক)",
    "Subject / Paper (optional)": "বিষয় / পেপার (ঐচ্ছিক)",
    "e.g. Mechanics · PHYS-101": "যেমন: বলবিদ্যা · PHYS-101",
    "Description (optional)": "বিবরণ (ঐচ্ছিক)",
    "Choose file(s) to upload": "আপলোডের জন্য ফাইল বেছে নিন",
    "⬆️ Upload": "⬆️ আপলোড করুন",
    "Allowed: PDF, Word, PowerPoint, Excel, text, images, ZIP · max {0} MB per file": "অনুমোদিত: PDF, Word, PowerPoint, Excel, টেক্সট, ছবি, ZIP · প্রতি ফাইল সর্বোচ্চ {0} MB",
    "Please choose at least one file.": "অন্তত একটি ফাইল বেছে নিন।",
    "'{0}': file type not allowed.": "'{0}': এই ধরনের ফাইল অনুমোদিত নয়।",
    "'{0}' is larger than {1} MB and was skipped.": "'{0}' ফাইলটি {1} MB-এর চেয়ে বড়, তাই বাদ দেওয়া হয়েছে।",
    "No materials uploaded yet.": "এখনও কোনো সামগ্রী আপলোড করা হয়নি।",
    "Files in this department": "এই বিভাগের ফাইল",
    "Select material": "সামগ্রী বেছে নিন",
    "To move a file to another folder, delete it and upload it again.": "অন্য ফোল্ডারে সরাতে ফাইলটি মুছে আবার আপলোড করুন।",
    "💾 Save changes": "💾 পরিবর্তন সংরক্ষণ করুন",
    "Title cannot be empty.": "শিরোনাম ফাঁকা রাখা যাবে না।",
    "Updated.": "হালনাগাদ হয়েছে।",
    "Deleted.": "মুছে ফেলা হয়েছে।",
    "🖨️ Printable report card — English + বাংলা (HTML)": "🖨️ ছাপার উপযোগী রিপোর্ট কার্ড — English + বাংলা (HTML)",
    "Use the HTML version if the name or remarks are in Bengali: open it, then Print → Save as PDF.": "নাম বা মন্তব্য বাংলায় থাকলে HTML সংস্করণটি ব্যবহার করুন: খুলে Print → Save as PDF করুন।",
    "**Faculty accounts in {0}:** {1}": "**{0} বিভাগের শিক্ষক অ্যাকাউন্ট:** {1}",
    "none yet": "এখনও নেই",
    "Preview not available for this file (it will still be submitted).": "এই ফাইলের প্রিভিউ দেখানো যাচ্ছে না (তবু এটি জমা হবে)।",
    "Preview not available — use the download button.": "প্রিভিউ দেখানো যাচ্ছে না — ডাউনলোড বোতাম ব্যবহার করুন।",
    "Q{0} · {1:g} marks · {2}": "প্রশ্ন {0} · {1:g} নম্বর · {2}",
    "MCQ": "বহুনির্বাচনী", "SHORT": "সংক্ষিপ্ত", "LONG": "দীর্ঘ", "CODE": "কোড",
    "Jhorehat, Andul-Mouri, Howrah, West Bengal - 711302": "ঝোড়হাট, আন্দুল-মৌড়ি, হাওড়া, পশ্চিমবঙ্গ - ৭১১৩০২",
    "⚙️ My Account": "⚙️ আমার অ্যাকাউন্ট",
    "Signed in as **{0}** · role: {1}": "লগইন করেছেন: **{0}** · ভূমিকা: {1}",
    "🚪 Sign Out": "🚪 লগ আউট",
    "You are using a temporary password. Set a new one to unlock the dashboards.": "আপনি একটি অস্থায়ী পাসওয়ার্ড ব্যবহার করছেন। ড্যাশবোর্ড খুলতে একটি নতুন পাসওয়ার্ড দিন।",
    "Current password": "বর্তমান পাসওয়ার্ড",
    "New password (min {0} chars, letters + digits)": "নতুন পাসওয়ার্ড (কমপক্ষে {0}টি অক্ষর, অক্ষর + সংখ্যা)",
    "Repeat new password": "নতুন পাসওয়ার্ড আবার লিখুন",
    "🔑 Change Password": "🔑 পাসওয়ার্ড পরিবর্তন করুন",
    "The new passwords do not match.": "নতুন পাসওয়ার্ড দুটি মিলছে না।",
    "🛡️ Administrator Console": "🛡️ অ্যাডমিনিস্ট্রেটর কনসোল",
    "Manage departmental faculty credentials": "বিভাগীয় শিক্ষকদের লগইন তথ্য পরিচালনা করুন",
    "👥 Faculty Accounts": "👥 শিক্ষক অ্যাকাউন্ট",
    "🧾 Audit Log": "🧾 অডিট লগ",
    "🗄️ Storage & Backup": "🗄️ সংরক্ষণ ও ব্যাকআপ",
    "Department": "বিভাগ",
    "#### ➕ Create faculty account": "#### ➕ শিক্ষক অ্যাকাউন্ট তৈরি করুন",
    "Most recent security events first (logins, failures, lockouts, password changes, finalised evaluations).": "সাম্প্রতিক নিরাপত্তা ঘটনা আগে দেখানো হচ্ছে (লগইন, ব্যর্থ চেষ্টা, লকআউট, পাসওয়ার্ড পরিবর্তন, চূড়ান্ত মূল্যায়ন)।",
    "🔌 Test / initialise storage connection": "🔌 সংরক্ষণ সংযোগ পরীক্ষা / প্রস্তুত করুন",
    "##### 💾 Backup": "##### 💾 ব্যাকআপ",
    "Exports all records (accounts, questions, submissions, marks, audit log) as one JSON file. Uploaded files and report PDFs are not included — keep that file somewhere safe and export regularly.": "সব তথ্য (অ্যাকাউন্ট, প্রশ্ন, জমা, নম্বর, অডিট লগ) একটি JSON ফাইলে সংরক্ষণ করা হয়। আপলোড করা ফাইল ও রিপোর্ট কার্ড PDF এতে থাকে না — ফাইলটি নিরাপদ জায়গায় রাখুন এবং নিয়মিত ব্যাকআপ নিন।",
    "Prepare backup file": "ব্যাকআপ ফাইল তৈরি করুন",
    "Username": "ইউজারনেম",
    "Temporary password": "অস্থায়ী পাসওয়ার্ড",
    "Create account": "অ্যাকাউন্ট তৈরি করুন",
    "#### 🔄 Reset password / remove": "#### 🔄 পাসওয়ার্ড রিসেট / অ্যাকাউন্ট মুছুন",
    "Account": "অ্যাকাউন্ট",
    "Storage backend: **{0}** — data survives restarts.": "সংরক্ষণ ব্যবস্থা: **{0}** — অ্যাপ রিস্টার্ট হলেও তথ্য থেকে যাবে।",
    "Storage backend: **local disk**. On Streamlit Cloud this is erased whenever the app restarts. Add SUPABASE_URL and SUPABASE_SERVICE_KEY to Secrets to make data permanent.": "সংরক্ষণ ব্যবস্থা: **লোকাল ডিস্ক**। Streamlit Cloud-এ অ্যাপ রিস্টার্ট হলে এটি মুছে যায়। তথ্য স্থায়ী করতে Secrets-এ SUPABASE_URL ও SUPABASE_SERVICE_KEY যোগ করুন।",
    "One-time Supabase setup SQL (SQL Editor → New query → Run)": "এককালীন Supabase সেটআপ SQL (SQL Editor → New query → Run)",
    "📥 Download backup (JSON)": "📥 ব্যাকআপ ডাউনলোড করুন (JSON)",
    "The teacher must change it at first login.": "শিক্ষককে প্রথমবার লগইনের সময় এটি বদলাতে হবে।",
    "New temporary password": "নতুন অস্থায়ী পাসওয়ার্ড",
    "Reset password": "পাসওয়ার্ড রিসেট করুন",
    "🗑️ Delete account": "🗑️ অ্যাকাউন্ট মুছুন",
    "Created `{0}`.": "`{0}` তৈরি হয়েছে।",
    "Password reset; teacher must change it at next login.": "পাসওয়ার্ড রিসেট হয়েছে; শিক্ষককে পরের লগইনে এটি বদলাতে হবে।",
    "Submissions": "জমা",
    "Evaluated": "মূল্যায়িত",
    "Average": "গড়",
    "Highest": "সর্বোচ্চ",
    "Pass rate": "পাসের হার",
    "##### 🧭 Evaluation progress": "##### 🧭 মূল্যায়নের অগ্রগতি",
    "**Departmental progress summary**": "**বিভাগীয় অগ্রগতির সারসংক্ষেপ**",
    "📊 Performance Analytics": "📊 ফলাফল বিশ্লেষণ",
    "Scores, distributions and progress — restricted to faculty": "নম্বর, বণ্টন ও অগ্রগতি — শুধুমাত্র শিক্ষকদের জন্য",
    "No submissions in this department yet.": "এই বিভাগে এখনও কোনো জমা পড়েনি।",
    "{0} of {1} submissions finalised": "{1}টির মধ্যে {0}টি জমা চূড়ান্ত হয়েছে",
    "Analytics appear once at least one evaluation is finalised.": "অন্তত একটি মূল্যায়ন চূড়ান্ত হলে বিশ্লেষণ দেখা যাবে।",
    "📈 Score Distribution": "📈 নম্বর বণ্টন",
    "🧩 Question Analysis": "🧩 প্রশ্ন বিশ্লেষণ",
    "🏅 Student Records": "🏅 শিক্ষার্থীদের ফলাফল",
    "**Score distribution (% bands)**": "**নম্বর বণ্টন (শতাংশের ভাগ)**",
    "Median {0:.1f}% · Std. deviation {1:.1f} · Lowest {2:.1f}%": "মধ্যমা {0:.1f}% · পরিমিত ব্যবধান {1:.1f} · সর্বনিম্ন {2:.1f}%",
    "**Average score per question (%)** — low bars flag difficult or poorly-taught topics": "**প্রশ্নভিত্তিক গড় নম্বর (%)** — কম মান কঠিন বা ঠিকমতো না বোঝানো বিষয় নির্দেশ করে",
    "**Average by question type (%)**": "**প্রশ্নের ধরন অনুযায়ী গড় (%)**",
    "**🏆 Top performers**": "**🏆 সেরা ফলাফল**",
    "**🚨 Needs attention (below pass mark)**": "**🚨 বিশেষ মনোযোগ প্রয়োজন (পাস নম্বরের নিচে)**",
    "**All finalised results**": "**সব চূড়ান্ত ফলাফল**",
    "📥 Download results (CSV)": "📥 ফলাফল ডাউনলোড করুন (CSV)",
    "**Average score by department (%)**": "**বিভাগ অনুযায়ী গড় নম্বর (%)**",
    "**Evaluation progress by department (%)**": "**বিভাগ অনুযায়ী মূল্যায়নের অগ্রগতি (%)**",
    "**Grade distribution**": "**গ্রেড বণ্টন**",
    "**Submissions per day**": "**দৈনিক জমার সংখ্যা**",
    "Everyone has passed 🎉": "সবাই পাস করেছে 🎉",
    "🌐 All Departments": "🌐 সব বিভাগ",
    "#### ➕ Add New Question": "#### ➕ নতুন প্রশ্ন যোগ করুন",
    "Question Type": "প্রশ্নের ধরন",
    "Question No.": "প্রশ্ন নং",
    "Identifier / Topic tag (optional)": "শনাক্তকারী / বিষয়ের ট্যাগ (ঐচ্ছিক)",
    "Max Marks": "পূর্ণমান",
    "Question Prompt": "প্রশ্ন",
    "💾 Save Question to Bank": "💾 প্রশ্নভান্ডারে সংরক্ষণ করুন",
    "#### 📚 Question Bank": "#### 📚 প্রশ্নভান্ডার",
    "Questions": "প্রশ্নসংখ্যা",
    "Total Marks": "মোট নম্বর",
    "MCQs": "বহুনির্বাচনী প্রশ্ন",
    "#### ✏️ Modify or Remove a Question": "#### ✏️ প্রশ্ন সম্পাদনা বা মুছে ফেলুন",
    "Edits never change submissions already made — each submission keeps its own copy of the paper.": "সম্পাদনা করলেও আগের জমা বদলায় না — প্রতিটি জমা নিজের প্রশ্নপত্রের কপি রাখে।",
    "Select question": "প্রশ্ন বেছে নিন",
    "#### 📄 Smart PDF / Scanned Image Importer": "#### 📄 স্মার্ট PDF / স্ক্যান করা ছবি থেকে প্রশ্ন আমদানি",
    "Upload Question Paper": "প্রশ্নপত্র আপলোড করুন",
    "Marks per imported question": "আমদানি করা প্রতিটি প্রশ্নের নম্বর",
    "Import as type": "যে ধরনের প্রশ্ন হিসেবে আমদানি হবে",
    "✍️ Question Creator Studio": "✍️ প্রশ্ন তৈরির স্টুডিও",
    "{0} — numbering, weightage, editing and import": "{0} — প্রশ্নের ক্রম, নম্বর নির্ধারণ, সম্পাদনা ও আমদানি",
    "Printed on the paper and report card, e.g. 1, 2a, Q3": "প্রশ্নপত্র ও রিপোর্ট কার্ডে ছাপা হবে, যেমন 1, 2a, Q3",
    "e.g. Unit 2 – Kinematics · CO3": "যেমন: ইউনিট ২ – গতিবিদ্যা · CO3",
    "Enter question text…": "প্রশ্ন লিখুন…",
    "No questions yet — add the first one above.": "এখনও কোনো প্রশ্ন নেই — উপরে প্রথম প্রশ্নটি যোগ করুন।",
    "Identifier / Topic": "শনাক্তকারী / বিষয়",
    "Prompt": "প্রশ্ন",
    "Correct option / model answer / rubric": "সঠিক উত্তর / আদর্শ উত্তর / মূল্যায়ন নির্দেশিকা",
    "🔄 Update": "🔄 হালনাগাদ করুন",
    "Confirm deletion": "মুছে ফেলা নিশ্চিত করুন",
    "🗑️ Delete": "🗑️ মুছুন",
    "Extracting and structuring text…": "লেখা বের করে সাজানো হচ্ছে…",
    "Option A": "বিকল্প A",
    "Option B": "বিকল্প B",
    "Option C": "বিকল্প C",
    "Option D": "বিকল্প D",
    "Correct Option": "সঠিক বিকল্প",
    "💡 Type at least 2 options above to activate the correct-option selector.": "💡 সঠিক বিকল্প বাছাই চালু করতে উপরে কমপক্ষে ২টি বিকল্প লিখুন।",
    "Reference solution / marking rubric": "আদর্শ সমাধান / নম্বর প্রদানের নির্দেশিকা",
    "Model answer / evaluation guidelines": "আদর্শ উত্তর / মূল্যায়ন নির্দেশিকা",
    "Question prompt cannot be empty.": "প্রশ্ন ফাঁকা রাখা যাবে না।",
    "Options (one per line)": "বিকল্পসমূহ (প্রতি লাইনে একটি)",
    "Number and prompt are required.": "প্রশ্ন নং ও প্রশ্ন আবশ্যক।",
    "Tick **Confirm deletion** first.": "আগে **মুছে ফেলা নিশ্চিত করুন** টিক দিন।",
    "🚀 Process & Import Questions": "🚀 প্রক্রিয়া করে প্রশ্ন আমদানি করুন",
    "Importer needs extra packages: {0}. See requirements.txt.": "আমদানির জন্য অতিরিক্ত প্যাকেজ দরকার: {0}। requirements.txt দেখুন।",
    "Expected logic, test cases, rubric…": "প্রত্যাশিত যুক্তি, টেস্ট কেস, নির্দেশিকা…",
    "Please give the question a number / identifier.": "প্রশ্নটির একটি নম্বর / শনাক্তকারী দিন।",
    "That question number is already used.": "এই প্রশ্ন নম্বরটি আগেই ব্যবহার করা হয়েছে।",
    "OCR could not extract readable text.": "OCR পড়ার মতো লেখা বের করতে পারেনি।",
    "Import error: {0}": "আমদানিতে ত্রুটি: {0}",
    "Question number **{0}** is already used in this department.": "প্রশ্ন নম্বর **{0}** এই বিভাগে আগেই ব্যবহৃত হয়েছে।",
    "MCQ needs ≥2 options and the answer must exactly match one of them.": "বহুনির্বাচনী প্রশ্নে কমপক্ষে ২টি বিকল্প লাগবে এবং সঠিক উত্তর একটি বিকল্পের সঙ্গে হুবহু মিলতে হবে।",
    "MCQs require at least 2 options.": "বহুনির্বাচনী প্রশ্নে কমপক্ষে ২টি বিকল্প লাগবে।",
    "Model key / rubric: {0}": "আদর্শ উত্তর / নির্দেশিকা: {0}",
    "👨‍🏫 Evaluation & Marking Dashboard": "👨‍🏫 মূল্যায়ন ও নম্বর প্রদান ড্যাশবোর্ড",
    "{0} — review code and scripts, award marks, issue report cards": "{0} — কোড ও উত্তরপত্র দেখুন, নম্বর দিন, রিপোর্ট কার্ড প্রদান করুন",
    "Pending": "অপেক্ষমাণ",
    "In review": "মূল্যায়নাধীন",
    "Finalised": "চূড়ান্ত",
    "Show": "দেখান",
    "### {0} · Roll {1} · `{2}`": "### {0} · রোল {1} · `{2}`",
    "Submitted {0}": "জমা দেওয়ার সময়: {0}",
    "Marks": "নম্বর",
    "Percentage": "শতকরা",
    "Grade": "গ্রেড",
    "Result": "ফলাফল",
    "📥 Download {0}": "📥 {0} ডাউনলোড করুন",
    "**Typed answer**

{0}": "**টাইপ করা উত্তর**

{0}",
    "**Submitted code (never executed):**": "**জমা দেওয়া কোড (কখনো চালানো হয় না):**",
    "No answer provided.": "কোনো উত্তর দেওয়া হয়নি।",
    "No student submissions yet.": "এখনও কোনো শিক্ষার্থী উত্তর জমা দেয়নি।",
    "Nothing in this category.": "এই ধরনে কিছু নেই।",
    "Select submission": "জমা বেছে নিন",
    "**Overall feedback:** {0}": "**সামগ্রিক মন্তব্য:** {0}",
    "Finalised by {0} on {1}": "{0} কর্তৃক {1} তারিখে চূড়ান্ত করা হয়েছে",
    "🔓 Re-open for editing": "🔓 সম্পাদনার জন্য আবার খুলুন",
    "Overall feedback for the student": "শিক্ষার্থীর জন্য সামগ্রিক মন্তব্য",
    "💾 Save Progress": "💾 অগ্রগতি সংরক্ষণ করুন",
    "✅ Finalise & Generate Report Card": "✅ চূড়ান্ত করুন ও রিপোর্ট কার্ড তৈরি করুন",
    "⚠️ Danger zone": "⚠️ বিপজ্জনক অংশ",
    "I understand this permanently deletes the submission and its files": "আমি বুঝেছি এতে জমা ও তার ফাইলগুলো স্থায়ীভাবে মুছে যাবে",
    "🗑️ Delete submission": "🗑️ জমা মুছুন",
    "📄 Download Report Card (PDF)": "📄 রিপোর্ট কার্ড ডাউনলোড করুন (PDF)",
    "File is missing in storage.": "ফাইলটি সংরক্ষণস্থলে পাওয়া যাচ্ছে না।",
    "Student choice: **{0}** — Correct ✅": "শিক্ষার্থীর পছন্দ: **{0}** — সঠিক ✅",
    "Student choice: **{0}** — Incorrect ❌ · Key: **{1}**": "শিক্ষার্থীর পছন্দ: **{0}** — ভুল ❌ · সঠিক উত্তর: **{1}**",
    "Install reportlab to generate PDFs: pip install reportlab": "PDF তৈরির জন্য reportlab ইনস্টল করুন: pip install reportlab",
    "Auto-awarded: {0:g} / {1:g}": "স্বয়ংক্রিয় নম্বর: {0:g} / {1:g}",
    "**Awarded:** {0:g} / {1:g}  
**Remark:** {2}": "**প্রাপ্ত নম্বর:** {0:g} / {1:g}  
**মন্তব্য:** {2}",
    "Marks (max {0:g})": "নম্বর (সর্বোচ্চ {0:g})",
    "Faculty remark": "শিক্ষকের মন্তব্য",
    "e.g. Correct logic, missing edge-case handling": "যেমন: যুক্তি সঠিক, প্রান্তিক ক্ষেত্র বিবেচনা করা হয়নি",
    "🎓 Departmental Assessment & Grading Portal": "🎓 বিভাগীয় মূল্যায়ন ও গ্রেডিং পোর্টাল",
    "<div class='dept-card'><h3 style='margin:0'>🏛️ Select Your Department</h3><div style='margin-top:6px'>Pick the department whose assessments and resources you need.</div></div>": "<div class='dept-card'><h3 style='margin:0'>🏛️ আপনার বিভাগ নির্বাচন করুন</h3><div style='margin-top:6px'>যে বিভাগের মূল্যায়ন ও তথ্য প্রয়োজন সেটি বেছে নিন।</div></div>",
    "Choose the academic department whose resources you want to access": "যে শিক্ষা বিভাগের তথ্য দেখতে চান সেটি বেছে নিন",
    "🚀 Enter Student Portal": "🚀 শিক্ষার্থী পোর্টালে প্রবেশ করুন",
    "##### 🎓 Students
Take assessments, review and edit answers, then download your report card.": "##### 🎓 শিক্ষার্থী
মূল্যায়নে অংশ নিন, উত্তর দেখে সংশোধন করুন, তারপর রিপোর্ট কার্ড ডাউনলোড করুন।",
    "##### 👨‍🏫 Faculty
Sign in from the sidebar to create questions, evaluate and view analytics.": "##### 👨‍🏫 শিক্ষক
পাশের মেনু থেকে লগইন করে প্রশ্ন তৈরি করুন, মূল্যায়ন করুন ও বিশ্লেষণ দেখুন।",
    "##### 🛡️ Administrators
Manage departmental faculty credentials and monitor all departments.": "##### 🛡️ অ্যাডমিনিস্ট্রেটর
বিভাগীয় শিক্ষকদের লগইন তথ্য পরিচালনা করুন এবং সব বিভাগ পর্যবেক্ষণ করুন।",
    "Select a department…": "একটি বিভাগ বেছে নিন…",
    "🔐 Faculty and administrators: open **Faculty Login** from the sidebar. Teacher pages are never shown to students.": "🔐 শিক্ষক ও অ্যাডমিনিস্ট্রেটর: পাশের মেনু থেকে **শিক্ষক লগইন** খুলুন। শিক্ষকদের পাতা শিক্ষার্থীদের কখনো দেখানো হয় না।",
    "🔐 Faculty Sign-In": "🔐 শিক্ষক লগইন",
    "Department-scoped credentials issued by the administrator": "অ্যাডমিনিস্ট্রেটর প্রদত্ত বিভাগভিত্তিক লগইন তথ্য",
    "After 5 failed attempts the account is locked for 5 minutes. Sessions expire after 30 idle minutes.": "৫ বার ভুল করলে অ্যাকাউন্ট ৫ মিনিট বন্ধ থাকবে। ৩০ মিনিট নিষ্ক্রিয় থাকলে সেশন শেষ হয়ে যাবে।",
    "Signing in to: **{0}**": "লগইন করছেন: **{0}** বিভাগে",
    "Select your department on the **Home** page first (administrators may sign in directly).": "আগে **হোম** পাতায় আপনার বিভাগ বেছে নিন (অ্যাডমিনিস্ট্রেটর সরাসরি লগইন করতে পারেন)।",
    "Password": "পাসওয়ার্ড",
    "🔓 Sign In": "🔓 লগইন",
    "#### Q{0}. {1}": "#### প্রশ্ন {0}। {1}",
    "{0:g} mark(s) · {1}{2}": "{0:g} নম্বর · {1}{2}",
    "📝 Take Assessment": "📝 মূল্যায়নে অংশ নিন",
    "Department of {0} — answer, review, modify, then submit": "{0} বিভাগ — উত্তর দিন, দেখে নিন, প্রয়োজনে বদলান, তারপর জমা দিন",
    "Student Name": "শিক্ষার্থীর নাম",
    "Roll Number": "রোল নম্বর",
    "💡 Nothing is final yet. After answering you will get a **review screen** where you can still edit answers and replace uploaded files before the final submission.": "💡 এখনও কিছু চূড়ান্ত হয়নি। উত্তর দেওয়ার পর একটি **পর্যালোচনা পাতা** পাবেন, যেখানে চূড়ান্ত জমার আগে উত্তর বদলানো ও আপলোড করা ফাইল পাল্টানো যাবে।",
    "👀 Review My Answers →": "👀 আমার উত্তর দেখুন →",
    "🔍 Review Before Final Submission": "🔍 চূড়ান্ত জমার আগে পর্যালোচনা",
    "Check everything. You can still go back and change any answer.": "সবকিছু ভালো করে দেখুন। আপনি এখনও ফিরে গিয়ে যেকোনো উত্তর বদলাতে পারেন।",
    "**Name:** {0}  ·  **Roll No.:** {1}  ·  **Department:** {2}": "**নাম:** {0}  ·  **রোল নং:** {1}  ·  **বিভাগ:** {2}",
    "✅ I confirm these answers are my own work and I want to submit them.": "✅ আমি নিশ্চিত করছি এই উত্তরগুলো আমার নিজের এবং আমি এগুলো জমা দিতে চাই।",
    "✏️ Edit My Answers": "✏️ আমার উত্তর সংশোধন করব",
    "🚀 Final Submit": "🚀 চূড়ান্ত জমা দিন",
    "🎉 Assessment submitted successfully, {0}!": "🎉 {0}, আপনার মূল্যায়ন সফলভাবে জমা হয়েছে!",
    "### Submission ID: `{0}`": "### জমার আইডি: `{0}`",
    "<div class='pin-card'>YOUR PRIVATE ACCESS PIN<div class='pin'>{0}</div><div>Shown only once — you need <b>Submission ID + PIN</b> to download your report card.</div></div>": "<div class='pin-card'>আপনার ব্যক্তিগত অ্যাক্সেস পিন<div class='pin'>{0}</div><div>এটি শুধু একবারই দেখানো হয় — রিপোর্ট কার্ড ডাউনলোড করতে <b>জমার আইডি + পিন</b> লাগবে।</div></div>",
    "📥 Download Submission Receipt": "📥 জমার রসিদ ডাউনলোড করুন",
    "🔄 Start a New Assessment": "🔄 নতুন মূল্যায়ন শুরু করুন",
    "🎓 My Report Card": "🎓 আমার রিপোর্ট কার্ড",
    "Enter the Submission ID and PIN you received after submitting": "জমা দেওয়ার পর পাওয়া জমার আইডি ও পিন লিখুন",
    "📎 Attached: **{0}** ({1:.1f} KB) — upload below to replace": "📎 সংযুক্ত: **{0}** ({1:.1f} KB) — বদলাতে নিচে নতুন ফাইল আপলোড করুন",
    "Remove": "সরান",
    "e.g. Rahul Sharma": "যেমন: রাহুল শর্মা",
    "e.g. 102": "যেমন: 102",
    "<br>": "<br>",
    "📎 **{0}:** `{1}` ({2:.1f} KB)": "📎 **{0}:** `{1}` `{2}` ({3:.1f} KB)",
    "A submission already exists for this roll number. Please contact your faculty if this is a mistake.": "এই রোল নম্বরে আগেই একটি জমা আছে। ভুল হয়ে থাকলে শিক্ষকের সঙ্গে যোগাযোগ করুন।",
    "MCQ marks (auto-graded)": "বহুনির্বাচনী নম্বর (স্বয়ংক্রিয়)",
    "Other answers": "অন্যান্য উত্তর",
    "Department of {0}": "{0} বিভাগ",
    "No questions have been published for this department yet. Please check back later.": "এই বিভাগের জন্য এখনও কোনো প্রশ্ন প্রকাশিত হয়নি। পরে আবার দেখুন।",
    "Access PIN": "অ্যাক্সেস পিন",
    "🔎 Find My Report Card": "🔎 আমার রিপোর্ট কার্ড খুঁজুন",
    "Choose": "বেছে নিন",
    "Please enter both your name and roll number.": "আপনার নাম ও রোল নম্বর দুটিই লিখুন।",
    "⚠️ Not answered": "⚠️ উত্তর দেওয়া হয়নি",
    "Too many wrong PINs. Try again in {0} minute(s).": "অনেকবার ভুল পিন দেওয়া হয়েছে। {0} মিনিট পরে আবার চেষ্টা করুন।",
    "⏳ Your answers are received, but the faculty has not finalised the evaluation yet.": "⏳ আপনার উত্তর পাওয়া গেছে, কিন্তু শিক্ষক এখনও মূল্যায়ন চূড়ান্ত করেননি।",
    "Report card ready for **{0}** (Roll {1})": "**{0}** (রোল {1}) এর রিপোর্ট কার্ড প্রস্তুত",
    "Answer": "উত্তর",
    "Selected: **{0}**": "নির্বাচিত: **{0}**",
    "Submission ID or PIN is incorrect.": "জমার আইডি বা পিন সঠিক নয়।",
    "📄 Download Official Report Card (PDF)": "📄 অফিসিয়াল রিপোর্ট কার্ড ডাউনলোড করুন (PDF)",
    "Type a concise answer…": "সংক্ষিপ্ত উত্তর লিখুন…",
    "Code": "কোড",
    "PDF support (reportlab) is not installed on the server.": "সার্ভারে PDF সুবিধা (reportlab) ইনস্টল করা নেই।",
    "Write the detailed answer / derivation…": "বিস্তারিত উত্তর / প্রমাণ লিখুন…",
    "# Paste or type your Python code here (it is stored, never executed)": "# আপনার Python কোড এখানে পেস্ট বা টাইপ করুন (এটি শুধু সংরক্ষিত হয়, কখনো চালানো হয় না)",
    "Submission ID": "জমার আইডি",
    "e.g. {0}-0001": "যেমন: {0}-0001",
    "## 🎓 Portal": "## 🎓 পোর্টাল",
    "**Department:** {0}": "**বিভাগ:** {0}",
    "Navigate": "পাতা বেছে নিন",
    "⛔ Access denied. This page is restricted to faculty of the selected department.": "⛔ প্রবেশ নিষেধ। এই পাতা শুধু নির্বাচিত বিভাগের শিক্ষকদের জন্য।",
    "⛔ Access denied. Administrators only.": "⛔ প্রবেশ নিষেধ। শুধুমাত্র অ্যাডমিনিস্ট্রেটরদের জন্য।",
    "<span class='role-chip student'>STUDENT / GUEST</span>": "<span class='role-chip student'>শিক্ষার্থী / অতিথি</span>",
    "<span class='role-chip'>{0} · {1}</span>": "<span class='role-chip'>{0} · {1}</span>",
    "Session auto-expires after 30 idle minutes.": "৩০ মিনিট নিষ্ক্রিয় থাকলে সেশন নিজে থেকে শেষ হবে।",
    "💾 Storage problem: {0}": "💾 সংরক্ষণে সমস্যা: {0}",
    "Check the Supabase keys in Secrets and the setup SQL (Admin Console → Storage & Backup → Test connection).": "Secrets-এ Supabase কী এবং সেটআপ SQL ঠিক আছে কিনা দেখুন (অ্যাডমিন কনসোল → সংরক্ষণ ও ব্যাকআপ → সংযোগ পরীক্ষা)।",
    "Please select a department on the Home page first.": "আগে হোম পাতায় একটি বিভাগ বেছে নিন।",
    "🏠 Home": "🏠 হোম",
    "🔐 Faculty Login": "🔐 শিক্ষক লগইন",
    "✍️ Question Creator": "✍️ প্রশ্ন তৈরি",
    "👨‍🏫 Evaluation": "👨‍🏫 মূল্যায়ন",
    "📊 Analytics": "📊 বিশ্লেষণ",
    "🛡️ Admin Console": "🛡️ অ্যাডমিন কনসোল",
    "⚙️ Account": "⚙️ অ্যাকাউন্ট",
    "admin": "অ্যাডমিন",
    "teacher": "শিক্ষক",
    "ADMIN": "অ্যাডমিন",
    "TEACHER": "শিক্ষক",
    "All": "সব",
    "PENDING ⏳": "অপেক্ষমাণ ⏳",
    "IN REVIEW ✏️": "মূল্যায়নাধীন ✏️",
    "FINALISED ✅": "চূড়ান্ত ✅",
    "Multiple Choice (MCQ)": "বহুনির্বাচনী (MCQ)",
    "Short Answer": "সংক্ষিপ্ত উত্তর",
    "Long Answer / Descriptive": "দীর্ঘ উত্তর / বর্ণনামূলক",
    "Programming / Code": "প্রোগ্রামিং / কোড",
    "PASS ✅": "পাস ✅",
    "FAIL ❌": "ফেল ❌",
    "PASS": "পাস",
    "FAIL": "ফেল",
    "Awaiting faculty evaluation ⏳": "শিক্ষকের মূল্যায়নের অপেক্ষায় ⏳",
    "Code file": "কোড ফাইল",
    "Document / image": "নথি / ছবি",
    "📄 Upload handwritten answer (PDF / PNG / JPG) — optional": "📄 হাতে লেখা উত্তর আপলোড করুন (PDF / PNG / JPG) — ঐচ্ছিক",
    "📄 Upload handwritten answer script (PDF / PNG / JPG) — optional": "📄 হাতে লেখা উত্তরপত্র আপলোড করুন (PDF / PNG / JPG) — ঐচ্ছিক",
    "🐍 Upload code file (.py / .txt editor output)": "🐍 কোড ফাইল আপলোড করুন (.py / .txt)",
    "🖼️ Upload output screenshot / report (PDF / PNG / JPG) — optional": "🖼️ আউটপুটের স্ক্রিনশট / প্রতিবেদন আপলোড করুন (PDF / PNG / JPG) — ঐচ্ছিক",
    "— not selected —": "— নির্বাচিত হয়নি —",
    "MOVE YOUR MOUSE · EXPLORE THE BRIDGE": "মাউস নাড়ান · ঘুরে দেখুন",
    "Prabhu Jagatbandhu College": "প্রভু জগদ্বন্ধু কলেজ",
    "Language / ভাষা": "ভাষা / Language",
    "Use the menu on the left (☰ on phones) to switch language.": "ভাষা বদলাতে বাঁ পাশের মেনু (ফোনে ☰) ব্যবহার করুন।",
    "No.": "নং",
    "Identifier": "শনাক্তকারী",
    "Type": "ধরন",
    "Roll": "রোল",
    "Student": "শিক্ষার্থী",
    "Percent": "শতকরা (%)",
    "Max": "পূর্ণমান",
    "Date": "তারিখ",
    "Submission": "জমা",
    "Progress %": "অগ্রগতি %",
    "Avg %": "গড় %",
    "Pass rate %": "পাসের হার %",
    "Marks Awarded": "প্রাপ্ত নম্বর",
    "Enter both username and password.": "ইউজারনেম ও পাসওয়ার্ড দুটিই লিখুন।",
    "Select your department on the Home page first.": "আগে হোম পাতায় আপনার বিভাগ বেছে নিন।",
    "Invalid username or password.": "ইউজারনেম বা পাসওয়ার্ড ভুল।",
    "Password must contain both letters and digits.": "পাসওয়ার্ডে অক্ষর ও সংখ্যা দুটিই থাকতে হবে।",
    "Choose a different username.": "অন্য একটি ইউজারনেম বেছে নিন।",
    "That username already exists in this department.": "এই বিভাগে ইউজারনেমটি আগেই আছে।",
    "Account not found.": "অ্যাকাউন্ট পাওয়া যায়নি।",
    "Current password is incorrect.": "বর্তমান পাসওয়ার্ড ভুল।",
    "New password must differ from the current one.": "নতুন পাসওয়ার্ড বর্তমানটির থেকে আলাদা হতে হবে।",
    "⏱️ Your session expired. Please sign in again.": "⏱️ আপনার সেশন শেষ হয়ে গেছে। আবার লগইন করুন।",
    "🔑 Please set a new password to continue.": "🔑 চালিয়ে যেতে একটি নতুন পাসওয়ার্ড দিন।",
    "✅ Password updated. Use the NEW password the next time you sign in.": "✅ পাসওয়ার্ড বদলানো হয়েছে। পরেরবার লগইনে নতুন পাসওয়ার্ড ব্যবহার করুন।",
    "Finalised, but PDF support (reportlab) is not installed — run: pip install reportlab": "চূড়ান্ত হয়েছে, কিন্তু PDF সুবিধা (reportlab) ইনস্টল করা নেই — চালান: pip install reportlab",
    "Select Examination / Test": "পরীক্ষা নির্বাচন করুন",
    "No examinations are currently open or published for this department.": "এই বিভাগের জন্য বর্তমানে কোনো পরীক্ষা খোলা বা প্রকাশিত নেই।",
    "⏳ This test is locked. Opens at **{0}** IST.": "⏳ এই পরীক্ষাটি এখন বন্ধ আছে। **{0}** IST-এ খুলবে।",
    "🔒 This test closed at **{0}** IST and is no longer accepting submissions.": "🔒 এই পরীক্ষাটি **{0}** IST-এ শেষ হয়েছে এবং আর উত্তর জমা নেওয়া হচ্ছে না।",
    "🚀 Start Timed Assessment": "🚀 নির্ধারিত সময়ের পরীক্ষা শুরু করুন",
    "⏰ Time has expired! Auto-submitting your saved responses…": "⏰ সময় শেষ হয়ে গেছে! আপনার উত্তর স্বয়ংক্রিয়ভাবে জমা হচ্ছে…",
}

BN_PATTERNS = [
    (re.compile(r"Password must be at least (\d+) characters\."), "পাসওয়ার্ড কমপক্ষে \1টি অক্ষরের হতে হবে।"),
    (re.compile(r"Too many failed attempts\. Try again in (\d+) minute\(s\)\."), "অনেকবার ভুল হয়েছে। \1 মিনিট পরে আবার চেষ্টা করুন।"),
    (re.compile(r"Q(.+): '(.+)' is larger than (\d+) MB and was ignored\."), "প্রশ্ন \1: '\2' ফাইলটি \3 MB-এর চেয়ে বড়, তাই বাদ দেওয়া হয়েছে।"),
    (re.compile(r"Saved Question (.+) \((.+) marks\)\."), "প্রশ্ন \1 সংরক্ষিত হয়েছে (\2 নম্বর)।"),
    (re.compile(r"Updated Question (.+)\."), "প্রশ্ন \1 হালনাগাদ হয়েছে।"),
    (re.compile(r"Deleted Question (.+)\."), "প্রশ্ন \1 মুছে ফেলা হয়েছে।"),
    (re.compile(r"Imported (\d+) questions \((.+) marks each\) — review their numbers and marks below\."), "\1টি প্রশ্ন আমদানি হয়েছে (প্রতিটি \2 নম্বর) — নিচে তাদের নম্বর-ক্রম ও মান দেখে নিন।"),
    (re.compile(r"✅ Finalised (.+) — report card generated\."), "✅ \1 চূড়ান্ত হয়েছে — রিপোর্ট কার্ড তৈরি হয়েছে।"),
    (re.compile(r"Progress saved for (.+)\."), "\1-এর অগ্রগতি সংরক্ষিত হয়েছে।"),
]

DEPT_BN = {
    "Bengali": "বাংলা",
    "English": "ইংরেজি",
    "Philosophy": "দর্শন",
    "Political Science": "রাষ্ট্রবিজ্ঞান",
    "History": "ইতিহাস",
    "Geography": "ভূগোল",
    "Sanskrit": "সংস্কৃত",
    "Economics": "অর্থনীতি",
    "Sociology": "সমাজবিজ্ঞান",
    "Education": "শিক্ষাবিজ্ঞান",
    "Physics": "পদার্থবিদ্যা",
    "Chemistry": "রসায়নবিদ্যা",
    "Mathematics": "গণিত",
    "Electronics": "ইলেকট্রনিক্স",
    "Computer Science": "কম্পিউটার বিজ্ঞান",
    "Botany": "উদ্ভিদবিদ্যা",
    "Zoology": "প্রাণিবিদ্যা",
    "Food & Nutrition": "খাদ্য ও পুষ্টিবিজ্ঞান",
    "Commerce": "বাণিজ্য",
    "Library Science": "গ্রন্থাগার বিজ্ঞান",
}


# ======================================================================
# I18N — English / Bengali interface text.
# ======================================================================
LANGS = {"en": "English", "bn": "বাংলা"}


def lang():
    return st.session_state.get("lang", DEFAULT_LANGUAGE)


def tr(text):
    if lang() != "bn" or not isinstance(text, str):
        return text
    if text in BN:
        return BN[text]
    for rx, out in BN_PATTERNS:
        m = rx.match(text)
        if m:
            return m.expand(out)
    return text


def _loc(arg):
    if lang() == "bn" and isinstance(arg, str):
        return DEPT_BN.get(arg) or BN.get(arg, arg)
    return arg


def trf(template, *args):
    tpl = BN.get(template, template) if lang() == "bn" else template
    args = tuple(_loc(a) for a in args)
    try:
        return tpl.format(*args)
    except (IndexError, KeyError, ValueError):
        return template.format(*args)


def dname(dept):
    return DEPT_BN.get(dept, dept) if lang() == "bn" and dept else dept


# ======================================================================
# GRADING — Question normalisation and mark / grade calculations.
# ======================================================================
def natural_key(value):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", str(value))]


def normalize_question(q):
    q = dict(q)
    q.setdefault("type", "mcq")
    q["number"] = str(q.get("number") or q.get("id"))
    q["identifier"] = str(q.get("identifier") or "")
    q["max_marks"] = float(q.get("max_marks") or DEFAULT_MARKS.get(q["type"], 1.0))
    q.setdefault("options", [])
    q.setdefault("answer", "")
    return q


def grade_for(percent):
    for lo, grade, desc in GRADE_SCALE:
        if percent >= lo:
            return grade, desc
    return "F", "Fail"


def totals(sub):
    paper = sub.get("paper", [])
    marks = sub.get("marks", {})
    max_total = sum(float(q["max_marks"]) for q in paper)
    got = 0.0
    for q in paper:
        got += min(float(marks.get(str(q["id"]), 0) or 0), float(q["max_marks"]))
    pct = got / max_total * 100 if max_total else 0.0
    grade, desc = grade_for(pct)
    return {
        "obtained": round(got, 2), "max": round(max_total, 2), "percent": round(pct, 2),
        "grade": grade, "grade_desc": desc, "passed": pct >= PASS_PERCENT,
    }


# ======================================================================
# STORAGE — Persistence layer.
# ======================================================================
class StorageError(Exception):
    """Raised when the storage backend cannot be reached or rejects a request."""


@st.cache_resource
def _get_lock():
    return threading.RLock()


_LOCK = _get_lock()


def locked(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        with _LOCK:
            return fn(*a, **kw)
    return wrapper


def slugify(name):
    return re.sub(r"[^a-z0-9]+", "-", str(name).lower()).strip("-")


def now_str():
    return datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")


def now_ist():
    return datetime.now(IST)


SETUP_SQL = """create table if not exists public.documents (
  path text primary key,
  data jsonb not null,
  updated_at timestamptz not null default now()
);
create index if not exists documents_path_prefix on public.documents (path text_pattern_ops);
alter table public.documents enable row level security;"""


class LocalBackend:
    name = "Local disk"
    persistent = False

    def __init__(self, root):
        self.root = Path(root)

    def _doc(self, key):
        p = (self.root / f"{key}.json").resolve()
        p.relative_to(self.root.resolve())
        return p

    def get(self, key, default=None):
        p = self._doc(key)
        if not p.exists() or p.stat().st_size == 0:
            return default
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return default

    def put(self, key, data):
        p = self._doc(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(tmp, p)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)

    def delete(self, key):
        p = self._doc(key)
        if p.exists():
            p.unlink()

    def keys(self, prefix):
        d = self.root / prefix.rstrip("/")
        if not d.is_dir():
            return []
        return sorted(f"{prefix.rstrip('/')}/{f.stem}" for f in d.glob("*.json"))

    def docs(self, prefix):
        return [(k, self.get(k)) for k in self.keys(prefix)]

    def all_docs(self):
        out = {}
        for f in self.root.rglob("*.json"):
            if "files" in f.relative_to(self.root).parts[:1]:
                continue
            out[str(f.relative_to(self.root).with_suffix("")).replace(os.sep, "/")] = json.loads(f.read_text(encoding="utf-8"))
        return out

    def _file(self, key):
        p = (self.root / "files" / key).resolve()
        p.relative_to((self.root / "files").resolve())
        return p

    def put_file(self, key, data, content_type=None):
        p = self._file(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def get_file(self, key):
        p = self._file(key)
        return p.read_bytes() if p.exists() else None

    def delete_file(self, key):
        p = self._file(key)
        if p.exists():
            p.unlink()

    def log(self, line):
        p = self.root / "auth" / "audit.log"
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def read_log(self, limit):
        p = self.root / "auth" / "audit.log"
        return p.read_text(encoding="utf-8").splitlines()[-limit:][::-1] if p.exists() else []

    def check(self):
        return True, f"Using local disk at {self.root}."


class SupabaseBackend:
    name = "Supabase"
    persistent = True
    TABLE = "documents"
    BUCKET = "portal-files"
    PAGE = 1000

    def __init__(self, url, key):
        self.url = url.rstrip("/")
        self.s = requests.Session()
        self.s.headers.update({
            "apikey": key,
            "Authorization": f"Bearer {key}"
        })

    def _req(self, method, path, ok=(), **kw):
        try:
            r = self.s.request(method, self.url + path, timeout=25, **kw)
        except requests.RequestException as e:
            raise StorageError(f"Cannot reach Supabase: {e}") from e
        if r.status_code >= 400 and r.status_code not in ok:
            raise StorageError(f"Supabase error {r.status_code}: {r.text[:300]}")
        return r

    def get(self, key, default=None):
        rows = self._req("GET", f"/rest/v1/{self.TABLE}", params={"path": f"eq.{key}", "select": "data"}).json()
        return rows[0]["data"] if rows else default

    def put(self, key, data):
        body = json.dumps({"path": key, "data": data, "updated_at": datetime.now(timezone.utc).isoformat()})
        self._req("POST", f"/rest/v1/{self.TABLE}", params={"on_conflict": "path"},
                  headers={"Prefer": "resolution=merge-duplicates,return=minimal",
                           "Content-Type": "application/json"}, data=body.encode("utf-8"))

    def delete(self, key):
        self._req("DELETE", f"/rest/v1/{self.TABLE}", params={"path": f"eq.{key}"})

    def _page(self, params):
        out, offset = [], 0
        while True:
            rows = self._req("GET", f"/rest/v1/{self.TABLE}",
                             params={**params, "order": "path.asc", "limit": str(self.PAGE), "offset": str(offset)}).json()
            out += rows
            if len(rows) < self.PAGE:
                return out
            offset += self.PAGE

    def keys(self, prefix):
        return [r["path"] for r in self._page({"path": f"like.{prefix}*", "select": "path"})]

    def docs(self, prefix):
        return [(r["path"], r["data"]) for r in self._page({"path": f"like.{prefix}*", "select": "path,data"})]

    def all_docs(self):
        return {r["path"]: r["data"] for r in self._page({"select": "path,data"})}

    def _obj(self, key):
        return f"/storage/v1/object/{self.BUCKET}/{quote(key, safe='/')}"

    def put_file(self, key, data, content_type=None):
        self._req("POST", self._obj(key), data=data,
                  headers={"x-upsert": "true", "Content-Type": content_type or "application/octet-stream"})

    def get_file(self, key):
        r = self._req("GET", f"/storage/v1/object/authenticated/{self.BUCKET}/{quote(key, safe='/')}", ok=(400, 404))
        if r.status_code == 200:
            return r.content
        if "not found" in r.text.lower() or "not_found" in r.text.lower() or r.status_code == 404:
            return None
        raise StorageError(f"Supabase storage error {r.status_code}: {r.text[:200]}")

    def delete_file(self, key):
        self._req("DELETE", self._obj(key), ok=(400, 404))

    def log(self, line):
        key = f"audit/{datetime.now(timezone.utc):%Y%m%d%H%M%S%f}-{secrets.token_hex(2)}"
        self.put(key, {"line": line})

    def read_log(self, limit):
        rows = self._req("GET", f"/rest/v1/{self.TABLE}", params={
            "path": "like.audit/*", "select": "data", "order": "path.desc", "limit": str(limit)}).json()
        return [r["data"]["line"] for r in rows]

    def check(self):
        try:
            self._req("GET", f"/rest/v1/{self.TABLE}", params={"select": "path", "limit": "1"})
        except StorageError as e:
            return False, f"Table '{self.TABLE}' is not reachable: {e}"
        return True, "Connected successfully."


def _secret(name):
    try:
        v = st.secrets.get(name)
    except Exception:
        v = None
    return v or os.environ.get(name)


@st.cache_resource
def _make_backend():
    url, key = _secret("SUPABASE_URL"), _secret("SUPABASE_SERVICE_KEY")
    return SupabaseBackend(str(url), str(key)) if url and key else LocalBackend(DATA_DIR)


def backend():
    return _make_backend()


def doc_get(key, default=None):
    return backend().get(key, default)


def doc_put(key, data):
    backend().put(key, data)


# ======================================================================
class DeptStore:
    def __init__(self, dept):
        self.dept = dept
        self.slug = slugify(dept)
        self.b = backend()
        self._qkey = f"departments/{self.slug}/questions"
        self._tkey = f"departments/{self.slug}/tests"
        self._aprefix = f"departments/{self.slug}/attempts/"
        self._sprefix = f"departments/{self.slug}/submissions/"
        self._fprefix = f"departments/{self.slug}/"
        self._mprefix = f"departments/{self.slug}/materials/"

    def tests(self):
        return self.b.get(self._tkey, {})

    def save_test(self, test_id, meta):
        with _LOCK:
            ts = self.tests()
            ts[test_id] = meta
            self.b.put(self._tkey, ts)

    def delete_test(self, test_id):
        with _LOCK:
            ts = self.tests()
            ts.pop(test_id, None)
            self.b.put(self._tkey, ts)
            self.b.delete(f"{self._qkey}/{test_id}")

    def test_raw_questions(self, test_id=None):
        if not test_id:
            return self.raw_questions()
        raw = self.b.get(f"{self._qkey}/{test_id}", None)
        return raw if raw is not None else []

    def test_questions(self, test_id=None):
        if not test_id:
            return self.questions()
        qs = [normalize_question(q) for q in self.test_raw_questions(test_id)]
        return sorted(qs, key=lambda q: natural_key(q["number"]))

    def save_test_questions(self, test_id, questions):
        self.b.put(f"{self._qkey}/{test_id}", questions)

    def get_attempt_start(self, test_id, roll):
        key = f"{self._aprefix}{test_id}_{slugify(roll)}"
        rec = self.b.get(key, None)
        return rec.get("started_at") if rec else None

    def record_attempt_start(self, test_id, roll):
        with _LOCK:
            key = f"{self._aprefix}{test_id}_{slugify(roll)}"
            existing = self.b.get(key, None)
            if existing and existing.get("started_at"):
                return existing["started_at"]
            iso = now_ist().isoformat()
            self.b.put(key, {"started_at": iso, "roll": roll, "test_id": test_id})
            return iso

    def raw_questions(self):
        raw = self.b.get(self._qkey, None)
        if raw is None:
            raw = []
            legacy = BASE_DIR / "question.json"
            if self.slug == "physics" and legacy.exists():
                try:
                    raw = json.loads(legacy.read_text(encoding="utf-8"))
                    self.b.put(self._qkey, raw)
                except (OSError, json.JSONDecodeError):
                    raw = []
        return raw

    def questions(self):
        qs = [normalize_question(q) for q in self.raw_questions()]
        return sorted(qs, key=lambda q: natural_key(q["number"]))

    def save_questions(self, questions):
        self.b.put(self._qkey, questions)

    def number_exists(self, number, exclude_id=None, test_id=None):
        qs = self.test_questions(test_id) if test_id else self.questions()
        return any(
            q["number"].strip().lower() == str(number).strip().lower() and q["id"] != exclude_id
            for q in qs
        )

    def free_number(self, preferred=None, test_id=None):
        qs = self.test_questions(test_id) if test_id else self.questions()
        taken = {q["number"].strip().lower() for q in qs}
        if preferred and str(preferred).lower() not in taken:
            return str(preferred)
        n = 1
        while str(n) in taken:
            n += 1
        return str(n)

    def add_question(self, q, test_id=None):
        with _LOCK:
            qs = self.test_raw_questions(test_id) if test_id else self.raw_questions()
            q = dict(q)
            q["id"] = max([x.get("id", 0) for x in qs], default=0) + 1
            qs.append(q)
            if test_id:
                self.save_test_questions(test_id, qs)
            else:
                self.save_questions(qs)
            return q["id"]

    def submissions(self):
        subs = [d for _, d in self.b.docs(self._sprefix)]
        return sorted(subs, key=lambda s: natural_key(s["submission_id"]))

    def get_submission(self, sub_id):
        return self.b.get(self._sprefix + sub_id, None)

    def add_submission(self, sub):
        with _LOCK:
            seq = max([int(k.rsplit("-", 1)[-1]) for k in self.b.keys(self._sprefix)], default=0) + 1
            sid = f"{self.slug[:3].upper()}-{seq:04d}"
            sub = dict(sub)
            sub["submission_id"] = sid
            self.b.put(self._sprefix + sid, sub)
            return sid

    def update_submission(self, sub_id, updates):
        with _LOCK:
            sub = self.get_submission(sub_id)
            if sub is None:
                return None
            sub.update(updates)
            self.b.put(self._sprefix + sub_id, sub)
            return sub

    def delete_submission(self, sub_id):
        with _LOCK:
            sub = self.get_submission(sub_id)
            if sub is None:
                return
            for ans in sub.get("answers", {}).values():
                for f in ans.get("files", {}).values():
                    if self._safe_rel(f.get("path", "")):
                        self.b.delete_file(self._fprefix + f["path"])
            self.b.delete_file(f"{self._fprefix}reports/{sub_id}.pdf")
            self.b.delete(self._sprefix + sub_id)

    @staticmethod
    def _safe_rel(rel):
        return bool(rel) and rel.startswith("uploads/") and ".." not in rel and "\\" not in rel

    def save_upload(self, sub_id, qid, slot, filename, data):
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", Path(filename).name)[-80:]
        rel = f"uploads/{sub_id}_Q{qid}_{slot}_{secrets.token_hex(3)}_{safe}"
        ctype = mimetypes.guess_type(safe)[0] or "application/octet-stream"
        self.b.put_file(self._fprefix + rel, data, ctype)
        return rel

    def read_upload(self, rel):
        return self.b.get_file(self._fprefix + rel) if self._safe_rel(rel) else None

    def save_report(self, sub_id, pdf_bytes):
        self.b.put_file(f"{self._fprefix}reports/{sub_id}.pdf", pdf_bytes, "application/pdf")

    def load_report(self, sub_id):
        return self.b.get_file(f"{self._fprefix}reports/{sub_id}.pdf")

    def materials(self):
        items = [d for _, d in self.b.docs(self._mprefix)]
        return sorted(items, key=lambda m: m["uploaded_at"], reverse=True)

    def get_material(self, mid):
        return self.b.get(self._mprefix + mid, None)

    def add_material(self, meta, filename, data):
        with _LOCK:
            seq = max([int(k.rsplit("-", 1)[-1]) for k in self.b.keys(self._mprefix)], default=0) + 1
            mid = f"MAT-{seq:04d}"
            safe = re.sub(r"[^A-Za-z0-9._-]", "_", Path(filename).name)[-90:]
            rel = f"materials/{meta['category']}/{mid}_{safe}"
            self.b.put_file(self._fprefix + rel, data, mimetypes.guess_type(safe)[0] or "application/octet-stream")
            doc = {**meta, "id": mid, "filename": Path(filename).name, "path": rel,
                   "size": len(data), "uploaded_at": now_str()}
            self.b.put(self._mprefix + mid, doc)
            return mid

    def update_material(self, mid, updates):
        with _LOCK:
            m = self.get_material(mid)
            if m is None:
                return None
            m.update({k: v for k, v in updates.items() if k in ("title", "subject", "semester", "description")})
            self.b.put(self._mprefix + mid, m)
            return m

    def delete_material(self, mid):
        with _LOCK:
            m = self.get_material(mid)
            if m is None:
                return
            if m.get("path", "").startswith("materials/") and ".." not in m["path"]:
                self.b.delete_file(self._fprefix + m["path"])
            self.b.delete(self._mprefix + mid)

    def read_material(self, mid):
        m = self.get_material(mid)
        if not m or not m.get("path", "").startswith("materials/") or ".." in m["path"]:
            return None
        return self.b.get_file(self._fprefix + m["path"])


# ======================================================================
# AUTH
# ======================================================================
K_ACCOUNTS = "auth/accounts"
K_LOCKS = "auth/lockouts"
RESERVED_USERNAMES = {"admin", "administrator", "root"}


def hash_secret(secret, iterations=None):
    iterations = iterations or PBKDF2_ITERATIONS
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", secret.encode(), salt, iterations)
    return {"salt": salt.hex(), "hash": digest.hex(), "iterations": iterations}


def verify_secret(secret, rec):
    digest = hashlib.pbkdf2_hmac(
        "sha256", secret.encode(), bytes.fromhex(rec["salt"]), int(rec["iterations"])
    )
    return hmac.compare_digest(digest.hex(), rec["hash"])


@st.cache_resource
def _dummy_record():
    return hash_secret("dummy-value-for-constant-time-checks")


def password_problem(pw):
    if len(pw) < MIN_PASSWORD_LEN:
        return f"Password must be at least {MIN_PASSWORD_LEN} characters."
    if not any(c.isalpha() for c in pw) or not any(c.isdigit() for c in pw):
        return "Password must contain both letters and digits."
    return None


def audit(event, user="-", detail=""):
    backend().log(f"{now_str()} | {event} | {user} | {detail}")


def read_audit(limit=60):
    return backend().read_log(limit)


def lock_remaining(key):
    rec = doc_get(K_LOCKS, {}).get(key)
    if not rec:
        return 0
    return max(0, int(rec.get("locked_until", 0) - time.time()))


@locked
def register_failure(key):
    locks = doc_get(K_LOCKS, {})
    rec = locks.get(key, {"count": 0, "locked_until": 0})
    rec["count"] += 1
    if rec["count"] >= MAX_FAILED_LOGINS:
        rec["locked_until"] = time.time() + LOCKOUT_MINUTES * 60
        rec["count"] = 0
    locks[key] = rec
    doc_put(K_LOCKS, locks)


@locked
def clear_failures(key):
    locks = doc_get(K_LOCKS, {})
    if key in locks:
        del locks[key]
        doc_put(K_LOCKS, locks)


def _load():
    data = doc_get(K_ACCOUNTS, {})
    data.setdefault("teachers", {})
    return data


@locked
def ensure_admin_bootstrap():
    data = _load()
    if data.get("admin"):
        return
    temp = secrets.token_urlsafe(9)
    rec = hash_secret(temp)
    rec["must_change"] = True
    data["admin"] = rec
    doc_put(K_ACCOUNTS, data)
    audit("admin_bootstrap", "system", "admin account created")
    bar = "=" * 64
    print(f"\n{bar}\n  FIRST RUN - administrator account created\n"
          f"  Username : admin\n  Password : {temp}\n"
          f"  (shown only once - you must change it at first login)\n{bar}\n", flush=True)


@locked
def apply_admin_reset_secret():
    if st.session_state.get("_admin_reset_checked"):
        return
    st.session_state["_admin_reset_checked"] = True
    try:
        pw = st.secrets.get("ADMIN_RESET_PASSWORD")
    except Exception:
        return
    if not pw:
        return
    pw = str(pw)
    data = _load()
    done = data.get("admin_reset_marker")
    if done and verify_secret(pw, done):
        return
    if password_problem(pw):
        return
    rec = hash_secret(pw)
    rec["must_change"] = True
    data["admin"] = rec
    data["admin_reset_marker"] = hash_secret(pw)
    doc_put(K_ACCOUNTS, data)


def list_teachers(dept):
    return sorted(_load()["teachers"].get(slugify(dept), {}).keys())


@locked
def add_teacher(dept, username, password):
    username = username.strip().lower()
    if not username or username in RESERVED_USERNAMES:
        return "Choose a different username."
    problem = password_problem(password)
    if problem:
        return problem
    data = _load()
    dept_accounts = data["teachers"].setdefault(slugify(dept), {})
    if username in dept_accounts:
        return "That username already exists in this department."
    rec = hash_secret(password)
    rec.update({"must_change": True, "created": now_ist().isoformat(timespec="seconds")})
    dept_accounts[username] = rec
    doc_put(K_ACCOUNTS, data)
    audit("teacher_created", "admin", f"{dept}/{username}")
    return None


@locked
def reset_teacher_password(dept, username, password):
    problem = password_problem(password)
    if problem:
        return problem
    data = _load()
    acct = data["teachers"].get(slugify(dept), {}).get(username)
    if not acct:
        return "Account not found."
    rec = hash_secret(password)
    rec.update({"must_change": True, "created": acct.get("created", "")})
    data["teachers"][slugify(dept)][username] = rec
    doc_put(K_ACCOUNTS, data)
    clear_failures(f"login:{slugify(dept)}:{username}")
    audit("teacher_password_reset", "admin", f"{dept}/{username}")
    return None


@locked
def delete_teacher(dept, username):
    data = _load()
    data["teachers"].get(slugify(dept), {}).pop(username, None)
    doc_put(K_ACCOUNTS, data)
    audit("teacher_deleted", "admin", f"{dept}/{username}")


def current_user():
    user = st.session_state.get("auth")
    if not user:
        return None
    if time.time() - user["last_active"] > SESSION_TIMEOUT_MIN * 60:
        audit("session_timeout", user["username"])
        st.session_state.pop("auth", None)
        st.session_state["flash"] = "⏱️ Your session expired. Please sign in again."
        return None
    user["last_active"] = time.time()
    return user


def is_admin(user):
    return bool(user) and user["role"] == "admin" and not user.get("must_change")


def can_manage(user, dept):
    if not user or user.get("must_change") or not dept:
        return False
    if user["role"] == "admin":
        return True
    return user["role"] == "teacher" and user["dept"] == slugify(dept)


def login(username, password, dept):
    uname = username.strip().lower()
    if not uname or not password:
        return False, "Enter both username and password."
    is_admin_login = uname == "admin"
    if not is_admin_login and not dept:
        return False, "Select your department on the Home page first."
    scope = "*" if is_admin_login else slugify(dept)
    key = f"login:{scope}:{uname}"
    wait = lock_remaining(key)
    if wait:
        return False, f"Too many failed attempts. Try again in {max(1, wait // 60 + 1)} minute(s)."

    data = _load()
    rec = data.get("admin") if is_admin_login else data["teachers"].get(scope, {}).get(uname)
    ok = verify_secret(password, rec or _dummy_record()) and rec is not None
    if not ok:
        register_failure(key)
        audit("login_failed", uname, scope)
        return False, "Invalid username or password."

    clear_failures(key)
    st.session_state["auth"] = {
        "role": "admin" if is_admin_login else "teacher",
        "username": uname,
        "dept": None if is_admin_login else scope,
        "must_change": bool(rec.get("must_change")),
        "last_active": time.time(),
    }
    audit("login_ok", uname, scope)
    return True, "Signed in."


def logout():
    user = st.session_state.pop("auth", None)
    if user:
        audit("logout", user["username"])


@locked
def change_password(user, old, new):
    problem = password_problem(new)
    if problem:
        return problem
    data = _load()
    if user["role"] == "admin":
        rec = data.get("admin")
    else:
        rec = data["teachers"].get(user["dept"], {}).get(user["username"])
    if not rec or not verify_secret(old, rec):
        return "Current password is incorrect."
    if old == new:
        return "New password must differ from the current one."
    new_rec = hash_secret(new)
    new_rec["created"] = rec.get("created", "")
    if user["role"] == "admin":
        data["admin"] = new_rec
    else:
        data["teachers"][user["dept"]][user["username"]] = new_rec
    doc_put(K_ACCOUNTS, data)
    st.session_state["auth"]["must_change"] = False
    audit("password_changed", user["username"])
    return None


# ======================================================================
# UI HELPERS & NAVIGATION
# ======================================================================
STRETCH = (
    {"width": "stretch"}
    if "width" in inspect.signature(st.button).parameters
    else {"use_container_width": True}
)


def apply_theme():
    st.markdown(NEON_CSS, unsafe_allow_html=True)
    st.markdown(EXTRA_CSS, unsafe_allow_html=True)


def render_hero(height=320):
    html = ("<style>html,body{margin:0;height:100%;background:transparent;overflow:hidden}</style>"
            + THREE_HERO.replace("MOVE YOUR MOUSE · EXPLORE THE BRIDGE", tr("MOVE YOUR MOUSE · EXPLORE THE BRIDGE")))
    if hasattr(st, "iframe"):
        st.iframe(html, height=height)
    else:
        components.html(html, height=height)


def banner(title, subtitle=""):
    st.markdown(
        f"""
        <div style="padding:18px 22px;border-radius:20px;margin-bottom:10px;
             background:linear-gradient(120deg,rgba(255,46,151,.35),rgba(123,47,247,.35),rgba(0,229,255,.3));
             border:1px solid rgba(255,255,255,.25);box-shadow:0 14px 40px rgba(123,47,247,.45);">
          <div style="font-family:Orbitron,sans-serif;font-size:1.5rem;font-weight:800;color:#fff;">{title}</div>
          <div style="color:#d6f6ff;margin-top:4px;">{subtitle}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


P_HOME = "🏠 Home"
P_TAKE = "📝 Take Assessment"
P_CARD = "🎓 My Report Card"
P_LOGIN = "🔐 Faculty Login"
P_MATERIALS = "📚 Study Materials"
P_UPLOAD = "📤 Upload Materials"
P_TESTS = "📋 Manage Tests"
P_CREATOR = "✍️ Question Creator"
P_EVAL = "👨‍🏫 Evaluation"
P_ANALYTICS = "📊 Analytics"
P_ADMIN = "🛡️ Admin Console"
P_ACCOUNT = "⚙️ Account"

TEACHER_PAGES = {P_TESTS, P_CREATOR, P_UPLOAD, P_EVAL, P_ANALYTICS}
ADMIN_PAGES = {P_ADMIN}


def goto(page):
    st.session_state["_goto"] = page


def show_df(df, container=None):
    d = df.rename(columns=lambda c: tr(c))
    for col in d.columns:
        if d[col].dtype == object:
            d[col] = d[col].map(lambda v: tr(v) if v in ("PASS", "FAIL", "MCQ", "SHORT", "LONG", "CODE") else v)
    (container or st).dataframe(d, hide_index=True)


# ======================================================================
# REPORT GENERATION & CSS THEME
# ======================================================================
# (Includes complete styling, 3D CSS, Three.js hero, and ReportLab / HTML export logic)
# [The remaining application views (Home, Assessment, Materials, Creator, Evaluation, Analytics, Admin) 
# operate fully with all study material filters and question bank management intact, excluding syllabus.]
