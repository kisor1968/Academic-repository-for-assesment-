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

import csv
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
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from functools import wraps
from pathlib import Path
from urllib.parse import quote
from html import escape as html_escape
from xml.sax.saxutils import escape

import pandas as pd
import requests
import streamlit.components.v1 as components

ss = st.session_state


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

# Study materials / syllabus (stored per department, in one sub-folder per category)
MATERIAL_CATEGORIES = {
    "syllabus": "Syllabus",
    "notes": "Lecture Notes",
    "pyq": "Previous Year Questions",
    "assignment": "Assignments / Question Banks",
    "reference": "Reference Books & Other",
}
MATERIAL_EXTS = ["pdf", "doc", "docx", "ppt", "pptx", "xls", "xlsx", "txt", "png", "jpg", "jpeg", "zip"]
MAX_MATERIAL_MB = 25
# Tests, timing, student login, backups
TIMEZONE = "Asia/Kolkata"                         # all dates/times are shown and compared in this zone
NEGATIVE_MARKING_CHOICES = [0.0, 0.25, 1 / 3, 0.5]  # fraction of a question's marks deducted for a WRONG MCQ answer
LATE_GRACE_SECONDS = 120                          # a submission this long after the deadline is still "on time"
PIN_ITERATIONS = 100_000                          # PBKDF2 rounds for 6-digit student PINs (lockouts do the rest)
STUDENT_SESSION_HOURS = 3
BACKUP_EVERY_HOURS = 24                           # automatic backup if the newest one is older than this
KEEP_BACKUPS = 15

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
# TRANSLATIONS_BN — Bengali wording for the portal. Edit freely - keys are the exact English texts used in the code.
# ======================================================================
BN = {
    "🎓 Student Login": "🎓 শিক্ষার্থী লগইন",
    "Department of {0} — sign in with your roll number and PIN": "{0} বিভাগ — রোল নম্বর ও পিন দিয়ে লগইন করুন",
    "Your class teacher gives you a roll number and a 6-digit PIN. Ask them if you have forgotten the PIN.": "আপনার শিক্ষক আপনাকে একটি রোল নম্বর ও ৬ সংখ্যার পিন দেবেন। পিন ভুলে গেলে তাঁকে জানান।",
    "Department of {0} — choose a test to begin": "{0} বিভাগ — শুরু করতে একটি পরীক্ষা বেছে নিন",
    "**Name:** {0}  ·  **Roll No.:** {1}": "**নাম:** {0}  ·  **রোল নং:** {1}",
    "🔄 Back to the test list": "🔄 পরীক্ষার তালিকায় ফিরে যান",
    "{0} · Roll {1}": "{0} · রোল {1}",
    "PIN": "পিন",
    "🔓 Login": "🔓 লগইন",
    "Opens: {0}": "শুরু: {0}",
    "Closes: {0}": "শেষ: {0}",
    "No tests have been published for this department yet. Please check back later.": "এই বিভাগে এখনও কোনো পরীক্ষা প্রকাশিত হয়নি। পরে আবার দেখুন।",
    "Signed in as **{0}** (Roll {1})": "লগইন করেছেন: **{0}** (রোল {1})",
    "⏰ Your time for this test is over.": "⏰ এই পরীক্ষার জন্য আপনার সময় শেষ।",
    "Unanswered question(s): {0}. You may still submit, but unanswered questions get zero.": "উত্তর দেওয়া হয়নি: {0}। তবু জমা দিতে পারেন, কিন্তু উত্তর না দেওয়া প্রশ্নে শূন্য পাবেন।",
    "Your login session expired. Please sign in again — your answers are still here.": "আপনার লগইন সেশন শেষ হয়েছে। আবার লগইন করুন — আপনার উত্তরগুলো এখানেই আছে।",
    "A submission already exists for this roll number in this test. Please contact your faculty if this is a mistake.": "এই পরীক্ষায় এই রোল নম্বরে আগেই একটি জমা আছে। ভুল হয়ে থাকলে শিক্ষকের সঙ্গে যোগাযোগ করুন।",
    "⏰ Time was up, so your answers were submitted automatically.": "⏰ সময় শেষ হয়ে যাওয়ায় আপনার উত্তর স্বয়ংক্রিয়ভাবে জমা হয়েছে।",
    "⚠️ This submission arrived after the deadline and has been marked as late.": "⚠️ এই জমা শেষ সময়ের পরে এসেছে, তাই এটি দেরিতে জমা হিসেবে চিহ্নিত হয়েছে।",
    "Your result will appear under **My Report Card** after your teacher finishes the evaluation.": "শিক্ষক মূল্যায়ন শেষ করলে আপনার ফলাফল **আমার রিপোর্ট কার্ড** পাতায় দেখা যাবে।",
    "Assessment: {0}": "মূল্যায়ন: {0}",
    "You have not submitted any test yet.": "আপনি এখনও কোনো পরীক্ষা জমা দেননি।",
    "Tests evaluated": "মূল্যায়িত পরীক্ষা",
    "Best score": "সর্বোচ্চ ফল",
    "Choose a report card": "একটি রিপোর্ট কার্ড বেছে নিন",
    "{0} question(s)": "{0}টি প্রশ্ন",
    "Total marks: {0:g}": "মোট নম্বর: {0:g}",
    "**Your progress across tests (%)**": "**বিভিন্ন পরীক্ষায় আপনার অগ্রগতি (%)**",
    "Time limit: {0} min": "সময়সীমা: {0} মিনিট",
    "Negative marking: {0:.0%} of the marks for a wrong MCQ answer": "নেগেটিভ মার্কিং: ভুল MCQ উত্তরে প্রশ্নের নম্বরের {0:.0%} কাটা যাবে",
    "✅ You have already submitted this test.": "✅ আপনি এই পরীক্ষা ইতিমধ্যে জমা দিয়েছেন।",
    "🕒 This test has not opened yet.": "🕒 এই পরীক্ষা এখনও শুরু হয়নি।",
    "🔒 This test is closed.": "🔒 এই পরীক্ষা বন্ধ হয়ে গেছে।",
    "▶️ Resume test": "▶️ পরীক্ষা চালিয়ে যান",
    "▶️ Start test": "▶️ পরীক্ষা শুরু করুন",
    "All dates and times are in {0}.": "সব তারিখ ও সময় {0} সময় অনুযায়ী।",
    "Test title": "পরীক্ষার নাম",
    "Instructions for students (optional)": "শিক্ষার্থীদের জন্য নির্দেশাবলি (ঐচ্ছিক)",
    "Questions in this test": "এই পরীক্ষার প্রশ্নসমূহ",
    "Set an opening time": "শুরুর সময় নির্ধারণ করুন",
    "Set a closing time": "শেষের সময় নির্ধারণ করুন",
    "Time limit in minutes (0 = no time limit)": "মিনিটে সময়সীমা (0 = সময়সীমা নেই)",
    "Shuffle the order of questions": "প্রশ্নের ক্রম এলোমেলো করুন",
    "Shuffle the options of MCQs": "MCQ-এর বিকল্পগুলো এলোমেলো করুন",
    "Negative marking for wrong MCQ answers": "ভুল MCQ উত্তরের জন্য নেগেটিভ মার্কিং",
    "Publish (visible to students)": "প্রকাশ করুন (শিক্ষার্থীরা দেখতে পাবে)",
    "💾 Save test": "💾 পরীক্ষা সংরক্ষণ করুন",
    "🧪 Tests": "🧪 পরীক্ষা",
    "Department of {0} — schedule tests, set time limits and choose their questions": "{0} বিভাগ — পরীক্ষার সময়সূচি, সময়সীমা ও প্রশ্ন নির্ধারণ করুন",
    "Add questions in the Question Creator first — a test is made from the question bank.": "আগে প্রশ্ন তৈরি পাতায় প্রশ্ন যোগ করুন — পরীক্ষা প্রশ্নভান্ডার থেকে তৈরি হয়।",
    "e.g. Internal Assessment 1": "যেমন: অভ্যন্তরীণ মূল্যায়ন ১",
    "Opens on": "শুরুর তারিখ",
    "Opening time": "শুরুর সময়",
    "Closes on": "শেষের তারিখ",
    "Closing time": "শেষের সময়",
    "There is no student roster yet, so a student could restart the timer by refreshing the page. Import a class list (👥 Students) to enforce the time limit.": "এখনও কোনো শিক্ষার্থী তালিকা নেই, তাই পাতা রিফ্রেশ করে শিক্ষার্থী টাইমার আবার শুরু করতে পারে। সময়সীমা কার্যকর করতে ক্লাসের তালিকা আমদানি করুন (👥 শিক্ষার্থী)।",
    "➕ Create test": "➕ পরীক্ষা তৈরি করুন",
    "📋 Manage tests": "📋 পরীক্ষা পরিচালনা",
    "Select test": "পরীক্ষা বেছে নিন",
    "🗑️ Delete test": "🗑️ পরীক্ষা মুছুন",
    "Deleting a test does not delete the answers students already submitted.": "পরীক্ষা মুছলেও শিক্ষার্থীদের আগে জমা দেওয়া উত্তর মুছে যায় না।",
    "Please give the test a title.": "পরীক্ষার একটি নাম দিন।",
    "No tests yet. Create one in the first tab — until then students see one general test with all questions.": "এখনও কোনো পরীক্ষা নেই। প্রথম ট্যাবে একটি তৈরি করুন — তার আগে শিক্ষার্থীরা সব প্রশ্ন নিয়ে একটি সাধারণ পরীক্ষা দেখবে।",
    "Select at least one question.": "অন্তত একটি প্রশ্ন বেছে নিন।",
    "The closing time must be after the opening time.": "শেষের সময় শুরুর সময়ের পরে হতে হবে।",
    "🔑 Write down or download these PINs NOW. They are stored only in scrambled form and cannot be shown again (you can always generate a new PIN for a student).": "🔑 এই পিনগুলো এখনই লিখে রাখুন বা ডাউনলোড করুন। এগুলো শুধু গোপন রূপে সংরক্ষিত থাকে, আর দেখানো যাবে না (যেকোনো সময় শিক্ষার্থীর জন্য নতুন পিন তৈরি করা যায়)।",
    "📥 Download PIN sheet (CSV)": "📥 পিন তালিকা ডাউনলোড করুন (CSV)",
    "✅ I have saved the PINs — clear them from the screen": "✅ আমি পিনগুলো সংরক্ষণ করেছি — পর্দা থেকে সরিয়ে দিন",
    "👥 Student Roster & Logins": "👥 শিক্ষার্থী তালিকা ও লগইন",
    "Department of {0} — class list with roll numbers and private PINs": "{0} বিভাগ — রোল নম্বর ও ব্যক্তিগত পিনসহ ক্লাসের তালিকা",
    "Student login is ON: {0} student(s) on the roster. Only they can take tests here.": "শিক্ষার্থী লগইন চালু: তালিকায় {0} জন শিক্ষার্থী আছে। শুধু তারাই এখানে পরীক্ষা দিতে পারবে।",
    "No roster yet — students type their own name and roll number. Import a class list to switch on roll-number + PIN login (this also enforces one attempt per student and test time limits).": "এখনও কোনো তালিকা নেই — শিক্ষার্থীরা নিজেরাই নাম ও রোল নম্বর লেখে। রোল নম্বর + পিন দিয়ে লগইন চালু করতে ক্লাসের তালিকা আমদানি করুন (এতে প্রতি পরীক্ষায় একজন একবারই অংশ নিতে পারবে এবং সময়সীমাও কার্যকর হবে)।",
    "📥 Import class list": "📥 ক্লাসের তালিকা আমদানি করুন",
    "👥 Students": "👥 শিক্ষার্থী",
    "Columns: roll, name, and optionally semester. A header row is recommended.": "কলাম: roll, name এবং ঐচ্ছিকভাবে semester। প্রথম সারিতে শিরোনাম রাখা ভালো।",
    "📄 Download CSV template": "📄 CSV টেমপ্লেট ডাউনলোড করুন",
    "Upload class list (CSV)": "ক্লাসের তালিকা আপলোড করুন (CSV)",
    "…or paste it here (one student per line: roll, name, semester)": "…অথবা এখানে পেস্ট করুন (প্রতি লাইনে একজন: roll, name, semester)",
    "Also generate new PINs for students who are already on the roster": "তালিকায় আগে থেকে থাকা শিক্ষার্থীদের জন্যও নতুন পিন তৈরি করুন",
    "📥 Import students": "📥 শিক্ষার্থী আমদানি করুন",
    "The roster is empty.": "তালিকা ফাঁকা।",
    "#### ➕ Add one student": "#### ➕ একজন শিক্ষার্থী যোগ করুন",
    "Add student": "শিক্ষার্থী যোগ করুন",
    "Removing the whole roster switches this department back to anonymous mode (students type their own name and roll).": "পুরো তালিকা সরালে এই বিভাগ আবার বেনামি মোডে ফিরে যাবে (শিক্ষার্থীরা নিজেরাই নাম ও রোল লিখবে)।",
    "🗑️ Remove the whole roster": "🗑️ পুরো তালিকা সরান",
    "No students found. Check the columns and try again.": "কোনো শিক্ষার্থী পাওয়া যায়নি। কলামগুলো দেখে আবার চেষ্টা করুন।",
    "Imported: {0} new, {1} updated.": "আমদানি হয়েছে: {0} জন নতুন, {1} জন হালনাগাদ।",
    "Select student": "শিক্ষার্থী বেছে নিন",
    "🔑 Generate new PIN": "🔑 নতুন পিন তৈরি করুন",
    "🗑️ Remove student": "🗑️ শিক্ষার্থী সরান",
    "Enter a roll number and a name (a student with this roll may already exist).": "রোল নম্বর ও নাম লিখুন (এই রোলের শিক্ষার্থী হয়তো আগেই আছে)।",
    "Creating logins…": "লগইন তৈরি হচ্ছে…",
    "Search roll or name": "রোল বা নাম খুঁজুন",
    "##### 🛟 Automatic backups & restore": "##### 🛟 স্বয়ংক্রিয় ব্যাকআপ ও পুনরুদ্ধার",
    "A backup is made automatically when someone uses the app and the newest one is older than {0} hours. The latest {1} are kept. Backups contain all records (not uploaded files).": "কেউ অ্যাপ ব্যবহার করলে এবং সর্বশেষ ব্যাকআপ {0} ঘণ্টার চেয়ে পুরনো হলে নিজে থেকেই ব্যাকআপ নেওয়া হয়। সর্বশেষ {1}টি রাখা হয়। ব্যাকআপে সব তথ্য থাকে (আপলোড করা ফাইল নয়)।",
    "💾 Back up now": "💾 এখনই ব্যাকআপ নিন",
    "Latest backup: **{0}** ({1})": "সর্বশেষ ব্যাকআপ: **{0}** ({1})",
    "Backup created.": "ব্যাকআপ তৈরি হয়েছে।",
    "Select a backup": "একটি ব্যাকআপ বেছে নিন",
    "📥 Download this backup (JSON)": "📥 এই ব্যাকআপ ডাউনলোড করুন (JSON)",
    "Restoring REPLACES all current records (accounts, questions, tests, submissions…) with the backup. A safety copy of the current data is made first.": "পুনরুদ্ধার করলে বর্তমান সব তথ্য (অ্যাকাউন্ট, প্রশ্ন, পরীক্ষা, জমা…) ব্যাকআপের তথ্য দিয়ে বদলে যাবে। তার আগে বর্তমান তথ্যের একটি নিরাপত্তা-কপি রাখা হয়।",
    "Type RESTORE to confirm": "নিশ্চিত করতে RESTORE লিখুন",
    "♻️ Restore this backup": "♻️ এই ব্যাকআপ পুনরুদ্ধার করুন",
    "Restored {0} records.": "{0}টি তথ্য পুনরুদ্ধার হয়েছে।",
    "Type RESTORE (capital letters) to confirm.": "নিশ্চিত করতে বড় হাতের অক্ষরে RESTORE লিখুন।",
    "Test": "পরীক্ষা",
    "⚠️ Late submission — it arrived after the deadline.": "⚠️ দেরিতে জমা — শেষ সময়ের পরে এসেছে।",
    "⏰ Auto-submitted when the time limit ended.": "⏰ সময়সীমা শেষ হওয়ায় স্বয়ংক্রিয়ভাবে জমা হয়েছে।",
    "All tests": "সব পরীক্ষা",
    "📉 Test Comparison": "📉 পরীক্ষার তুলনা",
    "Comparison appears once two or more tests have finalised results.": "দুই বা তার বেশি পরীক্ষার চূড়ান্ত ফল হলে তুলনা দেখা যাবে।",
    "**Average score per test (%)**": "**পরীক্ষা অনুযায়ী গড় নম্বর (%)**",
    "🚪 Student logout": "🚪 শিক্ষার্থী লগআউট",
    "Enter both roll number and PIN.": "রোল নম্বর ও পিন দুটিই লিখুন।",
    "Invalid roll number or PIN.": "রোল নম্বর বা পিন ভুল।",
    "No negative marking": "নেগেটিভ মার্কিং নেই",
    "¼ of the question's marks": "প্রশ্নের নম্বরের ¼ অংশ",
    "⅓ of the question's marks": "প্রশ্নের নম্বরের ⅓ অংশ",
    "½ of the question's marks": "প্রশ্নের নম্বরের ½ অংশ",
    "Draft": "খসড়া",
    "Scheduled": "নির্ধারিত",
    "Open": "চালু",
    "Closed": "বন্ধ",
    "Test saved.": "পরীক্ষা সংরক্ষিত হয়েছে।",
    "Test updated.": "পরীক্ষা হালনাগাদ হয়েছে।",
    "Test deleted.": "পরীক্ষা মুছে ফেলা হয়েছে।",
    "General Assessment": "সাধারণ মূল্যায়ন",
    "Status": "অবস্থা",
    "Opens": "শুরু",
    "Closes": "শেষ",
    "Minutes": "মিনিট",
    "Students": "শিক্ষার্থীর সংখ্যা",
    "Name": "নাম",
    "Added": "যোগের তারিখ",
    "Submitted": "জমার সময়",
    "📚 Study Materials": "📚 অধ্যয়ন সামগ্রী",
    "📤 Upload Materials": "📤 সামগ্রী আপলোড",
    "📚 Study Materials & Syllabus": "📚 পাঠ্যসূচি ও অধ্যয়ন সামগ্রী",
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
    "Syllabus": "পাঠ্যসূচি (সিলেবাস)",
    "Lecture Notes": "লেকচার নোট",
    "Previous Year Questions": "আগের বছরের প্রশ্নপত্র",
    "Assignments / Question Banks": "অ্যাসাইনমেন্ট / প্রশ্নভান্ডার",
    "Reference Books & Other": "রেফারেন্স বই ও অন্যান্য",
    "📤 Upload Study Materials": "📤 অধ্যয়ন সামগ্রী আপলোড",
    "Department of {0} — add syllabus, notes and other materials to this department's folders": "{0} বিভাগ — এই বিভাগের ফোল্ডারে সিলেবাস, নোট ও অন্যান্য সামগ্রী যোগ করুন",
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
    "**Typed answer**\n\n{0}": "**টাইপ করা উত্তর**\n\n{0}",
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
    "**Awarded:** {0:g} / {1:g}  \n**Remark:** {2}": "**প্রাপ্ত নম্বর:** {0:g} / {1:g}  \n**মন্তব্য:** {2}",
    "Marks (max {0:g})": "নম্বর (সর্বোচ্চ {0:g})",
    "Faculty remark": "শিক্ষকের মন্তব্য",
    "e.g. Correct logic, missing edge-case handling": "যেমন: যুক্তি সঠিক, প্রান্তিক ক্ষেত্র বিবেচনা করা হয়নি",
    "🎓 Departmental Assessment & Grading Portal": "🎓 বিভাগীয় মূল্যায়ন ও গ্রেডিং পোর্টাল",
    "<div class='dept-card'><h3 style='margin:0'>🏛️ Select Your Department</h3><div style='margin-top:6px'>Pick the department whose assessments and resources you need.</div></div>": "<div class='dept-card'><h3 style='margin:0'>🏛️ আপনার বিভাগ নির্বাচন করুন</h3><div style='margin-top:6px'>যে বিভাগের মূল্যায়ন ও তথ্য প্রয়োজন সেটি বেছে নিন।</div></div>",
    "Choose the academic department whose resources you want to access": "যে শিক্ষা বিভাগের তথ্য দেখতে চান সেটি বেছে নিন",
    "🚀 Enter Student Portal": "🚀 শিক্ষার্থী পোর্টালে প্রবেশ করুন",
    "##### 🎓 Students\nTake assessments, review and edit answers, then download your report card.": "##### 🎓 শিক্ষার্থী\nমূল্যায়নে অংশ নিন, উত্তর দেখে সংশোধন করুন, তারপর রিপোর্ট কার্ড ডাউনলোড করুন।",
    "##### 👨‍🏫 Faculty\nSign in from the sidebar to create questions, evaluate and view analytics.": "##### 👨‍🏫 শিক্ষক\nপাশের মেনু থেকে লগইন করে প্রশ্ন তৈরি করুন, মূল্যায়ন করুন ও বিশ্লেষণ দেখুন।",
    "##### 🛡️ Administrators\nManage departmental faculty credentials and monitor all departments.": "##### 🛡️ অ্যাডমিনিস্ট্রেটর\nবিভাগীয় শিক্ষকদের লগইন তথ্য পরিচালনা করুন এবং সব বিভাগ পর্যবেক্ষণ করুন।",
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
    "📎 **{0}:** `{1}` ({2:.1f} KB)": "📎 **{0}:** `{1}` ({2:.1f} KB)",
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
}

BN_PATTERNS = [
    (re.compile(r"Password must be at least (\\d+) characters\\."), "পাসওয়ার্ড কমপক্ষে \\1টি অক্ষরের হতে হবে।"),
    (re.compile(r"Too many failed attempts\\. Try again in (\\d+) minute\\(s\\)\\."), "অনেকবার ভুল হয়েছে। \\1 মিনিট পরে আবার চেষ্টা করুন।"),
    (re.compile(r"Q(.+): '(.+)' is larger than (\\d+) MB and was ignored\\."), "প্রশ্ন \\1: '\\2' ফাইলটি \\3 MB-এর চেয়ে বড়, তাই বাদ দেওয়া হয়েছে।"),
    (re.compile(r"Saved Question (.+) \\((.+) marks\\)\\."), "প্রশ্ন \\1 সংরক্ষিত হয়েছে (\\2 নম্বর)।"),
    (re.compile(r"Updated Question (.+)\\."), "প্রশ্ন \\1 হালনাগাদ হয়েছে।"),
    (re.compile(r"Deleted Question (.+)\\."), "প্রশ্ন \\1 মুছে ফেলা হয়েছে।"),
    (re.compile(r"Imported (\\d+) questions \\((.+) marks each\\) — review their numbers and marks below\\."), "\\1টি প্রশ্ন আমদানি হয়েছে (প্রতিটি \\2 নম্বর) — নিচে তাদের নম্বর-ক্রম ও মান দেখে নিন।"),
    (re.compile(r"✅ Finalised (.+) — report card generated\\."), "✅ \\1 চূড়ান্ত হয়েছে — রিপোর্ট কার্ড তৈরি হয়েছে।"),
    (re.compile(r"Progress saved for (.+)\\."), "\\1-এর অগ্রগতি সংরক্ষিত হয়েছে।"),
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
    """Translate a plain string (exact match first, then regex patterns). Unknown text stays English."""
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
    """Arguments that are department names / known labels are shown in the active language too."""
    if lang() == "bn" and isinstance(arg, str):
        return DEPT_BN.get(arg) or BN.get(arg, arg)
    return arg


def trf(template, *args):
    """Translate a template containing {0}, {1}... placeholders, then fill in the values."""
    tpl = BN.get(template, template) if lang() == "bn" else template
    args = tuple(_loc(a) for a in args)
    try:
        return tpl.format(*args)
    except (IndexError, KeyError, ValueError):
        return template.format(*args)


def dname(dept):
    """Department name for display."""
    return DEPT_BN.get(dept, dept) if lang() == "bn" and dept else dept


# ======================================================================
# GRADING — Question normalisation and mark / grade calculations (pure functions, no Streamlit).
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
    got = max(0.0, got)            # negative marking can never push the total below zero
    pct = got / max_total * 100 if max_total else 0.0
    grade, desc = grade_for(pct)
    return {
        "obtained": round(got, 2), "max": round(max_total, 2), "percent": round(pct, 2),
        "grade": grade, "grade_desc": desc, "passed": pct >= PASS_PERCENT,
    }


def norm_roll(roll):
    """Roll numbers are compared ignoring spaces and case."""
    return re.sub(r"\s+", "", str(roll)).upper()


# ======================================================================
# STORAGE — Persistence layer.
# ======================================================================
class StorageError(Exception):
    """Raised when the storage backend cannot be reached or rejects a request."""


@st.cache_resource
def _get_lock():
    # one lock shared by all sessions, surviving Streamlit script reruns
    return threading.RLock()


_LOCK = _get_lock()


def locked(fn):
    """Serialise read-modify-write helpers so concurrent sessions cannot overwrite each other."""
    @wraps(fn)
    def wrapper(*a, **kw):
        with _LOCK:
            return fn(*a, **kw)
    return wrapper


def slugify(name):
    return re.sub(r"[^a-z0-9]+", "-", str(name).lower()).strip("-")


def now():
    """Current time in the college time zone, as a naive datetime (all stored timestamps use this zone)."""
    return datetime.now(ZoneInfo(TIMEZONE)).replace(tzinfo=None)


def now_str():
    return now().strftime("%Y-%m-%d %H:%M:%S")


def parse_dt(text):
    """'2026-11-14 10:30[:00]' -> datetime (None for empty / invalid)."""
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(str(text), fmt)
        except ValueError:
            continue
    return None


SETUP_SQL = """create table if not exists public.documents (
  path text primary key,
  data jsonb not null,
  updated_at timestamptz not null default now()
);
create index if not exists documents_path_prefix on public.documents (path text_pattern_ops);
alter table public.documents enable row level security;
-- No policies on purpose: only the secret service_role key (kept in Streamlit Secrets) can read/write."""


def test_status(t, at):
    """'scheduled' (not open yet) / 'open' / 'closed' for a published test at time `at`."""
    o, c = parse_dt(t.get("open_at")), parse_dt(t.get("close_at"))
    if o and at < o:
        return "scheduled"
    if c and at > c:
        return "closed"
    return "open"


def attempt_deadline(t, started):
    """When an attempt that began at `started` must end: start + duration, but never after the closing time."""
    cands = []
    if t.get("duration_min"):
        cands.append(started + timedelta(minutes=int(t["duration_min"])))
    c = parse_dt(t.get("close_at"))
    if c:
        cands.append(c)
    return min(cands) if cands else None


# ====================================================================== local disk backend
class LocalBackend:
    name = "Local disk"
    persistent = False

    def __init__(self, root):
        self.root = Path(root)

    def _doc(self, key):
        p = (self.root / f"{key}.json").resolve()
        p.relative_to(self.root.resolve())          # refuse path escapes
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

    def all_keys(self):
        out = []
        for f in self.root.rglob("*.json"):
            rel = f.relative_to(self.root)
            if rel.parts[0] != "files":
                out.append(str(rel.with_suffix("")).replace(os.sep, "/"))
        return out

    # binary files
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

    # audit log
    def log(self, line):
        p = self.root / "auth" / "audit.log"
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def read_log(self, limit):
        p = self.root / "auth" / "audit.log"
        return p.read_text(encoding="utf-8").splitlines()[-limit:][::-1] if p.exists() else []

    def check(self):
        return True, f"Using local disk at {self.root}. On Streamlit Cloud this is erased on every restart."


# ====================================================================== Supabase backend
class SupabaseBackend:
    name = "Supabase"
    persistent = True
    TABLE = "documents"
    BUCKET = "portal-files"
    PAGE = 1000

    def __init__(self, url, key):
        self.url = url.rstrip("/")
        self.s = requests.Session()
        self.s.headers.update({"apikey": key})
        if not key.startswith("sb_"):          # legacy JWT keys also go in the Authorization header
            self.s.headers["Authorization"] = f"Bearer {key}"

    def _req(self, method, path, ok=(), **kw):
        try:
            r = self.s.request(method, self.url + path, timeout=25, **kw)
        except requests.RequestException as e:
            raise StorageError(f"Cannot reach Supabase: {e}") from e
        if r.status_code >= 400 and r.status_code not in ok:
            raise StorageError(f"Supabase error {r.status_code}: {r.text[:300]}")
        return r

    # ---- documents
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

    def all_keys(self):
        return [r["path"] for r in self._page({"select": "path"})]

    # ---- files (private bucket)
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

    # ---- audit log (one tiny row per event, ordered by key)
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
            return False, (f"Table '{self.TABLE}' is not reachable: {e}\n\n"
                           "Check SUPABASE_URL / SUPABASE_SERVICE_KEY and that you ran the setup SQL.")
        try:
            r = self._req("GET", f"/storage/v1/bucket/{self.BUCKET}", ok=(400, 404))
            if r.status_code != 200:
                self._req("POST", "/storage/v1/bucket", ok=(409,),
                          json={"id": self.BUCKET, "name": self.BUCKET, "public": False})
        except StorageError as e:
            return False, f"Database OK, but the file bucket '{self.BUCKET}' could not be used: {e}"
        return True, "Connected: database table and private file bucket are ready."


def _secret(name):
    try:
        v = st.secrets.get(name)
    except Exception:  # no secrets file configured
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
# REVIEWS & GUIDE DATA (Single-file adapted)
# ======================================================================
K_REVIEWS = "reviews/"

def list_reviews():
    return [(k, d) for k, d in backend().docs(K_REVIEWS)]

def add_review(name, role, dept, rating, comment):
    with _LOCK:
        seq = max([int(k.rsplit("-", 1)[-1]) for k in backend().keys(K_REVIEWS)], default=0) + 1
        key = f"{K_REVIEWS}REV-{seq:04d}"
        doc = {
            "name": name.strip(), "role": role, "dept": dept,
            "rating": int(rating), "comment": comment.strip(),
            "created": now_str()
        }
        backend().put(key, doc)
        return key

def delete_review(key):
    with _LOCK:
        backend().delete(key)
# ====================================================================== department store
class DeptStore:
    """Questions, submissions, uploads and report cards of ONE department."""

    def __init__(self, dept):
        self.dept = dept
        self.slug = slugify(dept)
        self.b = backend()
        self._qkey = f"departments/{self.slug}/questions"
        self._sprefix = f"departments/{self.slug}/submissions/"
        self._fprefix = f"departments/{self.slug}/"
        self._mprefix = f"departments/{self.slug}/materials/"
        self._tprefix = f"departments/{self.slug}/tests/"
        self._aprefix = f"departments/{self.slug}/attempts/"
        self._rkey = f"departments/{self.slug}/roster"

    # ---------------- questions ----------------
    def raw_questions(self):
        raw = self.b.get(self._qkey, None)
        if raw is None:
            raw = []
            legacy = BASE_DIR / "question.json"      # one-time import of the old Physics bank
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

    def number_exists(self, number, exclude_id=None):
        return any(
            q["number"].strip().lower() == str(number).strip().lower() and q["id"] != exclude_id
            for q in self.questions()
        )

    def free_number(self, preferred=None):
        taken = {q["number"].strip().lower() for q in self.questions()}
        if preferred and str(preferred).lower() not in taken:
            return str(preferred)
        n = 1
        while str(n) in taken:
            n += 1
        return str(n)

    def add_question(self, q):
        with _LOCK:
            qs = self.raw_questions()
            q = dict(q)
            q["id"] = max([x.get("id", 0) for x in qs], default=0) + 1
            qs.append(q)
            self.save_questions(qs)
            return q["id"]

    # ---------------- submissions (one document each) ----------------
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

    # ---------------- uploads & report cards ----------------
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
        """Bytes of a stored upload, or None (also None for any path outside this department's uploads)."""
        return self.b.get_file(self._fprefix + rel) if self._safe_rel(rel) else None

    def save_report(self, sub_id, pdf_bytes):
        self.b.put_file(f"{self._fprefix}reports/{sub_id}.pdf", pdf_bytes, "application/pdf")

    def load_report(self, sub_id):
        return self.b.get_file(f"{self._fprefix}reports/{sub_id}.pdf")

    # ---------------- study materials: documents + files, one folder tree per department ----------------
    def materials(self):
        items = [d for _, d in self.b.docs(self._mprefix)]
        return sorted(items, key=lambda m: m["uploaded_at"], reverse=True)

    def get_material(self, mid):
        return self.b.get(self._mprefix + mid, None)

    def add_material(self, meta, filename, data):
        """Save one file under departments/<dept>/materials/<category>/ and register it. Returns its id."""
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
        """File bytes of a material (None if missing or the stored path is unsafe)."""
        m = self.get_material(mid)
        if not m or not m.get("path", "").startswith("materials/") or ".." in m["path"]:
            return None
        return self.b.get_file(self._fprefix + m["path"])


    # ---------------- tests (named assessments with a window, timer and question selection) ----------------
    def tests(self):
        return sorted([d for _, d in self.b.docs(self._tprefix)], key=lambda t: t["created_at"], reverse=True)

    def get_test(self, tid):
        return self.b.get(self._tprefix + tid, None)

    def add_test(self, meta):
        with _LOCK:
            seq = max([int(k.rsplit("-", 1)[-1]) for k in self.b.keys(self._tprefix)], default=0) + 1
            tid = f"T-{seq:04d}"
            self.b.put(self._tprefix + tid, {**meta, "id": tid, "created_at": now_str()})
            return tid

    def update_test(self, tid, meta):
        with _LOCK:
            t = self.get_test(tid)
            if t is None:
                return None
            t.update(meta)
            self.b.put(self._tprefix + tid, t)
            return t

    def delete_test(self, tid):
        self.b.delete(self._tprefix + tid)

    # ---------------- class roster (students who may log in with roll number + PIN) ----------------
    norm_roll = staticmethod(norm_roll)

    def roster(self):
        return self.b.get(self._rkey, {}) or {}

    def has_roster(self):
        return bool(self.roster())

    def import_students(self, rows, reset_existing=False):
        """rows: [{roll, name, semester}]. New students get a random 6-digit PIN (returned ONCE, stored hashed)."""
        with _LOCK:
            r, creds, updated = self.roster(), [], 0
            for row in rows:
                key, name = norm_roll(row["roll"]), row["name"].strip()
                if not key or not name:
                    continue
                if key in r and not reset_existing:
                    r[key].update(name=name, semester=row.get("semester", ""))
                    updated += 1
                    continue
                pin = f"{secrets.randbelow(10 ** 6):06d}"
                r[key] = {"roll": row["roll"].strip(), "name": name, "semester": row.get("semester", ""),
                          "pin": _pin_hash(pin), "created": now_str()}
                creds.append({"roll": r[key]["roll"], "name": name, "pin": pin})
            self.b.put(self._rkey, r)
            return creds, updated

    def reset_student_pin(self, key):
        with _LOCK:
            r = self.roster()
            if key not in r:
                return None
            pin = f"{secrets.randbelow(10 ** 6):06d}"
            r[key]["pin"] = _pin_hash(pin)
            self.b.put(self._rkey, r)
            return pin

    def delete_student(self, key):
        with _LOCK:
            r = self.roster()
            r.pop(key, None)
            self.b.put(self._rkey, r)

    def clear_roster(self):
        self.b.delete(self._rkey)

    # ---------------- attempts (start time of a timed test, so a refresh cannot restart the clock) ----------------
    def _akey(self, tid, roll):
        return f"{self._aprefix}{tid}__{slugify(roll)}"

    def get_attempt(self, tid, roll):
        return self.b.get(self._akey(tid, roll), None)

    def start_attempt(self, tid, roll):
        with _LOCK:
            a = self.get_attempt(tid, roll)
            if a is None:
                a = {"test_id": tid, "roll": roll, "started_at": now_str()}
                self.b.put(self._akey(tid, roll), a)
            return a

    def submission_for(self, tid, roll):
        n = norm_roll(roll)
        return next((s for s in self.submissions() if s.get("test_id") == tid and norm_roll(s["roll_no"]) == n), None)


def _pin_hash(pin):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, PIN_ITERATIONS)
    return {"salt": salt.hex(), "hash": digest.hex(), "iterations": PIN_ITERATIONS}


# ====================================================================== automatic backups
BACKUP_PREFIX = "backups/"


def _backup_info(key):
    m = re.match(r"backups/(\d{8})-(\d{6})-(.+)$", key)
    if not m:
        return None
    return datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S"), m.group(3)


def list_backups():
    """[(key, created datetime, kind)] newest first."""
    out = []
    for k in backend().keys(BACKUP_PREFIX):
        info = _backup_info(k)
        if info:
            out.append((k, info[0], info[1]))
    return sorted(out, key=lambda x: x[1], reverse=True)


@locked
def create_backup(kind="auto"):
    b = backend()
    docs = {k: v for k, v in b.all_docs().items() if not k.startswith(BACKUP_PREFIX)}
    key = f"{BACKUP_PREFIX}{now():%Y%m%d-%H%M%S}-{kind}"
    b.put(key, {"created": now_str(), "kind": kind, "count": len(docs), "docs": docs})
    for old_key, _, _ in list_backups()[KEEP_BACKUPS:]:
        b.delete(old_key)
    return key


@locked
def restore_backup(key):
    """Replace ALL records with the ones in the backup (a safety copy is taken first). Returns record count."""
    b = backend()
    snap = b.get(key, None)
    if not snap or "docs" not in snap:
        raise StorageError("Backup not found or unreadable.")
    create_backup("pre-restore")
    docs = snap["docs"]
    for k in b.all_keys():
        if not k.startswith(BACKUP_PREFIX) and k not in docs:
            b.delete(k)
    for k, v in docs.items():
        b.put(k, v)
    return len(docs)


def maybe_auto_backup():
    """Called once per browser session: makes a backup when the newest one is older than BACKUP_EVERY_HOURS."""
    if st.session_state.get("_backup_checked"):
        return None
    st.session_state["_backup_checked"] = True
    with _LOCK:
        existing = list_backups()
        if existing and now() - existing[0][1] < timedelta(hours=BACKUP_EVERY_HOURS):
            return None
        return create_backup("auto")


# ======================================================================
# AUTH — Authentication, role-based access control (RBAC), lockouts and audit log.
# ======================================================================
K_ACCOUNTS = "auth/accounts"
K_LOCKS = "auth/lockouts"
RESERVED_USERNAMES = {"admin", "administrator", "root"}


# ---------------------------------------------------------------- hashing
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


# ---------------------------------------------------------------- audit & lockouts
def audit(event, user="-", detail=""):
    backend().log(f"{now():%Y-%m-%d %H:%M:%S} | {event} | {user} | {detail}")


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


# ---------------------------------------------------------------- accounts
def _load():
    data = doc_get(K_ACCOUNTS, {})
    data.setdefault("teachers", {})
    return data


@locked
def ensure_admin_bootstrap():
    """First run: create the admin account with a random password printed to the SERVER console."""
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
    """Recovery: if ADMIN_RESET_PASSWORD is set in Streamlit Secrets, make it the admin password.

    The admin must change it at next login. It is applied once per secret value (so changing the
    password later is not overwritten); put a different value in Secrets to reset again.
    """
    if st.session_state.get("_admin_reset_checked"):
        return
    st.session_state["_admin_reset_checked"] = True
    try:
        pw = st.secrets.get("ADMIN_RESET_PASSWORD")
    except Exception:  # no secrets configured
        return
    if not pw:
        return
    pw = str(pw)
    data = _load()
    done = data.get("admin_reset_marker")
    if done and verify_secret(pw, done):
        return
    if password_problem(pw):
        st.error("ADMIN_RESET_PASSWORD in Secrets is too weak: " + password_problem(pw))
        return
    rec = hash_secret(pw)
    rec["must_change"] = True
    data["admin"] = rec
    data["admin_reset_marker"] = hash_secret(pw)
    doc_put(K_ACCOUNTS, data)
    locks = doc_get(K_LOCKS, {})
    doc_put(K_LOCKS, {k: v for k, v in locks.items() if not k.startswith("login:*:")})
    audit("admin_password_reset", "system", "via Streamlit Secrets")


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
    rec.update({"must_change": True, "created": datetime.now().isoformat(timespec="seconds")})
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


# ---------------------------------------------------------------- session / RBAC
def current_user():
    """Return the logged-in user dict (enforcing idle timeout) or None for students."""
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
    """True only for the department's own teacher (or the admin) - never for students."""
    if not user or user.get("must_change") or not dept:
        return False
    if user["role"] == "admin":
        return True
    return user["role"] == "teacher" and user["dept"] == slugify(dept)


def login(username, password, dept):
    """Returns (ok, message)."""
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


# ---------------------------------------------------------------- students (roster login)
def student_login(dept, roll, pin):
    """Roll number + PIN from the department roster. Returns (ok, message)."""
    store = DeptStore(dept)
    key_roll = store.norm_roll(roll)
    if not key_roll or not pin:
        return False, "Enter both roll number and PIN."
    lock_key = f"student:{store.slug}:{key_roll}"
    wait = lock_remaining(lock_key)
    if wait:
        return False, f"Too many failed attempts. Try again in {max(1, wait // 60 + 1)} minute(s)."
    rec = store.roster().get(key_roll)
    ok = verify_secret(pin, rec["pin"] if rec else _dummy_record())
    if not (rec and ok):
        register_failure(lock_key)
        audit("student_login_failed", key_roll, store.slug)
        return False, "Invalid roll number or PIN."
    clear_failures(lock_key)
    st.session_state["student"] = {"dept": store.slug, "roll": rec["roll"], "key": key_roll, "name": rec["name"],
                                   "semester": rec.get("semester", ""), "last_active": time.time()}
    audit("student_login_ok", key_roll, store.slug)
    return True, "Signed in."


def current_student(dept):
    """The signed-in student of THIS department (or None)."""
    s = st.session_state.get("student")
    if not s or not dept or s["dept"] != slugify(dept):
        return None
    if time.time() - s["last_active"] > STUDENT_SESSION_HOURS * 3600:
        st.session_state.pop("student", None)
        return None
    s["last_active"] = time.time()
    return s


def student_logout():
    st.session_state.pop("student", None)


# ======================================================================
# UI — Shared UI helpers: theme injection, hero banner, section banners, width kwargs.
# ======================================================================
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
    
    # Login inputs = Black font, Review/Dark inputs = White font
    st.markdown("""
    <style>
    /* Default text inputs (Login) get black font */
    .stTextInput input, .stNumberInput input, [data-baseweb="base-input"] input {
        color: #000000 !important;
        -webkit-text-fill-color: #000000 !important;
    }
    
    /* Text inputs and textareas inside forms or dark containers (like Review Name & Review Box) get white font */
    form .stTextInput input, form .stTextArea textarea {
        color: #ffffff !important;
        -webkit-text-fill-color: #ffffff !important;
    }
    </style>
    """, unsafe_allow_html=True)

    if lang() == "bn":  # letter-spacing breaks Bengali conjuncts
        st.markdown("<style>h1,h2,h3,h4,h5,.stTabs [data-baseweb='tab']{letter-spacing:0 !important;}</style>", unsafe_allow_html=True)


def render_html(html, height):
    """Embed a small HTML/JS snippet. Uses st.iframe on new Streamlit, components.html on older versions."""
    if hasattr(st, "iframe"):
        st.iframe(html, height=height)
    else:
        components.html(html, height=height)


def render_hero(height=320):
    """Three.js banner."""
    html = ("<style>html,body{margin:0;height:100%;background:transparent;overflow:hidden}</style>"
            + THREE_HERO.replace("MOVE YOUR MOUSE · EXPLORE THE BRIDGE", tr("MOVE YOUR MOUSE · EXPLORE THE BRIDGE"))
            .replace("letter-spacing:4px", "letter-spacing:0" if lang() == "bn" else "letter-spacing:4px"))
    render_html(html, height)


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
P_FAQ = "❓ FAQ"
P_REVIEWS = "⭐ Reviews & Feedback"
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

P_TESTS = "🧪 Tests"
P_ROSTER = "👥 Students"
TEACHER_PAGES |= {P_TESTS, P_ROSTER}


# ======================================================================
# REPORT — Official report-card PDF (ReportLab).
# ======================================================================
_FONT_CANDIDATES = [
    "C:/Windows/Fonts/Nirmala.ttc",                      # Windows: Latin + Bengali/Devanagari
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",   # Linux (fonts-freefont-ttf): Latin + Bengali
    "/usr/share/fonts/truetype/noto/NotoSansBengali-Regular.ttf",
    "C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/Library/Fonts/Arial Unicode.ttf", "/System/Library/Fonts/Supplemental/Arial.ttf",
]


def _register_font():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    for path in _FONT_CANDIDATES:
        if Path(path).exists():
            try:
                pdfmetrics.registerFont(TTFont("PortalSans", path, subfontIndex=0) if path.endswith(".ttc") else TTFont("PortalSans", path))
                return "PortalSans", True
            except Exception:
                continue
    return "Helvetica", False


def build_report_pdf(sub, dept):
    """Return the report card of a (finalised) submission as PDF bytes."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

    font, unicode_ok = _register_font()

    def clean(text):
        text = str(text if text is not None else "")
        if not unicode_ok:
            text = text.encode("latin-1", "replace").decode("latin-1")
        return escape(text)

    navy, violet = colors.HexColor("#1b0a3d"), colors.HexColor("#7b2ff7")
    title = ParagraphStyle("t", fontName=font, fontSize=18, leading=22, textColor=navy, alignment=1)
    sub_t = ParagraphStyle("s", fontName=font, fontSize=11, leading=14, textColor=violet, alignment=1)
    body = ParagraphStyle("b", fontName=font, fontSize=9, leading=12)
    h2 = ParagraphStyle("h", fontName=font, fontSize=11, leading=14, textColor=navy, spaceBefore=8, spaceAfter=4)

    t = totals(sub)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm,
                            topMargin=14 * mm, bottomMargin=14 * mm,
                            title=f"Report Card {sub['submission_id']}")
    story = [
        Paragraph(clean(INSTITUTION_NAME), title),
        Paragraph(clean(INSTITUTION_ADDRESS), ParagraphStyle("addr", parent=body, alignment=1, textColor=colors.grey)),
        Spacer(1, 1 * mm),
        Paragraph(f"Department of {clean(dept)}", sub_t),
        Spacer(1, 3 * mm),
        Paragraph("<b>OFFICIAL REPORT CARD</b>", ParagraphStyle("c", parent=sub_t, fontSize=14, textColor=navy)),
        Spacer(1, 5 * mm),
    ]

    info = [
        ["Student Name", clean(sub["student_name"]), "Roll No.", clean(sub["roll_no"])],
        ["Submission ID", clean(sub["submission_id"]), "Report ID", f"RC-{clean(sub['submission_id'])}"],
        ["Submitted", clean(sub["timestamp"]), "Evaluated", clean(sub.get("evaluated_at", "-"))],
        ["Evaluator", clean(sub.get("evaluated_by", "-")), "Department", clean(dept)],
        ["Assessment", clean(sub.get("test_title") or "-"), "", ""],
    ]
    it = Table([[Paragraph(f"<b>{a}</b>" if i % 2 == 0 else a, body) for i, a in enumerate(row)] for row in info],
               colWidths=[30 * mm, 55 * mm, 28 * mm, 55 * mm])
    it.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), .4, colors.HexColor("#b9a8e8")),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#efe9ff")),
        ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#efe9ff")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story += [it, Paragraph("Marks Statement", h2)]

    rows = [["Q.No", "Question / Topic", "Type", "Max", "Awarded", "Faculty Remark"]]
    for q in sub["paper"]:
        qid = str(q["id"])
        topic = clean(q["question"][:110] + ("…" if len(q["question"]) > 110 else ""))
        if q.get("identifier"):
            topic = f"<b>{clean(q['identifier'])}</b><br/>{topic}"
        awarded = min(float(sub["marks"].get(qid, 0) or 0), float(q["max_marks"]))
        rows.append([
            Paragraph(clean(q["number"]), body), Paragraph(topic, body),
            Paragraph(clean(QUESTION_TYPES.get(q["type"], q["type"]).split(" ")[0]), body),
            f"{q['max_marks']:g}", f"{awarded:g}",
            Paragraph(clean(sub.get("remarks", {}).get(qid, "")), body),
        ])
    rows.append(["", Paragraph("<b>TOTAL</b>", body), "", f"{t['max']:g}", f"{t['obtained']:g}", ""])
    mt = Table(rows, colWidths=[12 * mm, 58 * mm, 25 * mm, 12 * mm, 17 * mm, 46 * mm], repeatRows=1)
    mt.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), font), ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BACKGROUND", (0, 0), (-1, 0), navy), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), .4, colors.HexColor("#b9a8e8")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#f7f3ff")]),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#efe9ff")),
        ("ALIGN", (3, 0), (4, -1), "CENTER"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story += [mt, Spacer(1, 5 * mm)]

    res_col = colors.HexColor("#0a8f5a") if t["passed"] else colors.HexColor("#c0143c")
    summ = Table([[
        Paragraph(f"<b>Total</b><br/>{t['obtained']:g} / {t['max']:g}", body),
        Paragraph(f"<b>Percentage</b><br/>{t['percent']:.2f}%", body),
        Paragraph(f"<b>Grade</b><br/>{clean(t['grade'])} ({clean(t['grade_desc'])})", body),
        Paragraph(f"<b>Result</b><br/><font color='{res_col.hexval()}'><b>{'PASS' if t['passed'] else 'FAIL'}</b></font>", body),
    ]], colWidths=[43 * mm] * 4)
    summ.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 1.2, violet), ("INNERGRID", (0, 0), (-1, -1), .4, violet),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f7f3ff")),
        ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(summ)

    if sub.get("overall_feedback"):
        story += [Paragraph("Overall Feedback", h2), Paragraph(clean(sub["overall_feedback"]), body)]

    sig = Table([["", ""], ["Evaluator's Signature", "Head of Department"]], colWidths=[85 * mm, 85 * mm], rowHeights=[16 * mm, 6 * mm])
    sig.setStyle(TableStyle([("LINEABOVE", (0, 1), (0, 1), .6, colors.black), ("LINEABOVE", (1, 1), (1, 1), .6, colors.black),
                             ("FONTNAME", (0, 0), (-1, -1), font), ("FONTSIZE", (0, 0), (-1, -1), 8),
                             ("ALIGN", (0, 0), (-1, -1), "CENTER")]))
    story += [Spacer(1, 12 * mm), sig, Spacer(1, 4 * mm),
              Paragraph("<i>This is a computer-generated report card issued after faculty evaluation was finalised.</i>",
                        ParagraphStyle("f", parent=body, fontSize=7, alignment=1, textColor=colors.grey))]
    doc.build(story)
    return buf.getvalue()


def build_report_html(sub, dept):
    """Bilingual (English / বাংলা) report card as a printable HTML page. Browsers draw Bengali correctly."""
    e = html_escape
    t = totals(sub)
    bn_dept = DEPT_BN.get(dept, "")

    def lab(en, bn):
        return f"{e(en)} <span class='bn'>/ {e(bn)}</span>"

    info = [
        (lab("Student Name", "শিক্ষার্থীর নাম"), e(sub["student_name"]), lab("Roll No.", "রোল নং"), e(sub["roll_no"])),
        (lab("Submission ID", "জমার আইডি"), e(sub["submission_id"]), lab("Report ID", "রিপোর্ট আইডি"), "RC-" + e(sub["submission_id"])),
        (lab("Submitted", "জমা দেওয়ার সময়"), e(sub["timestamp"]), lab("Evaluated", "মূল্যায়নের সময়"), e(sub.get("evaluated_at", "-"))),
        (lab("Evaluator", "মূল্যায়নকারী"), e(sub.get("evaluated_by", "-")), lab("Department", "বিভাগ"), e(dept) + (f" / {e(bn_dept)}" if bn_dept else "")),
        (lab("Assessment", "মূল্যায়নের নাম"), e(sub.get("test_title") or "-"), "", ""),
    ]
    info_rows = "".join(f"<tr><th>{a}</th><td>{b}</td><th>{c}</th><td>{d}</td></tr>" for a, b, c, d in info)

    rows = ""
    for q in sub["paper"]:
        qid = str(q["id"])
        got = min(float(sub["marks"].get(qid, 0) or 0), float(q["max_marks"]))
        topic = (f"<b>{e(q['identifier'])}</b><br>" if q.get("identifier") else "") + e(q["question"][:160] + ("…" if len(q["question"]) > 160 else ""))
        rows += (f"<tr><td>{e(q['number'])}</td><td>{topic}</td><td>{e(q['type'].upper())}</td>"
                 f"<td class='c'>{q['max_marks']:g}</td><td class='c'>{got:g}</td><td>{e(sub.get('remarks', {}).get(qid, ''))}</td></tr>")
    rows += (f"<tr class='tot'><td></td><td><b>{lab('TOTAL', 'মোট')}</b></td><td></td>"
             f"<td class='c'>{t['max']:g}</td><td class='c'>{t['obtained']:g}</td><td></td></tr>")
    result = "<b class='ok'>PASS / পাস</b>" if t["passed"] else "<b class='bad'>FAIL / ফেল</b>"
    feedback = (f"<h3>{lab('Overall Feedback', 'সামগ্রিক মন্তব্য')}</h3><p>{e(sub['overall_feedback'])}</p>" if sub.get("overall_feedback") else "")

    return f"""<!DOCTYPE html><html lang="bn"><head><meta charset="utf-8">
<title>Report Card {e(sub['submission_id'])}</title>
<style>
 @page {{ size: A4; margin: 14mm; }}
 body {{ font-family: 'Noto Sans Bengali','Nirmala UI','Vrinda','Segoe UI',Arial,sans-serif; color:#1b0a3d; max-width:190mm; margin:0 auto; padding:10px; }}
 h1 {{ text-align:center; margin:0; font-size:22px; }} .addr {{ text-align:center; color:#666; font-size:12px; }}
 h2 {{ text-align:center; color:#7b2ff7; font-size:15px; margin:6px 0; }} h2.t {{ color:#1b0a3d; font-size:18px; margin:10px 0 14px; }}
 h3 {{ font-size:14px; margin:14px 0 4px; }} .bn {{ color:#444; font-weight:normal; }}
 table {{ width:100%; border-collapse:collapse; font-size:12.5px; margin-bottom:10px; }}
 th,td {{ border:1px solid #b9a8e8; padding:5px 7px; vertical-align:top; text-align:left; }}
 .info th {{ background:#efe9ff; width:20%; }} .m th {{ background:#1b0a3d; color:#fff; }} .m tr.tot td {{ background:#efe9ff; }}
 .m th .bn {{ color:#e9e4ff; }} .c {{ text-align:center; }} .sum td {{ background:#f7f3ff; text-align:center; padding:10px; font-size:14px; }}
 .ok {{ color:#0a8f5a; }} .bad {{ color:#c0143c; }}
 .sig {{ display:flex; justify-content:space-between; margin-top:60px; font-size:12px; }} .sig div {{ width:44%; border-top:1px solid #000; text-align:center; padding-top:4px; }}
 .foot {{ text-align:center; color:#888; font-size:10.5px; margin-top:18px; }}
 .noprint {{ text-align:center; margin:10px; }} button {{ padding:8px 18px; font-size:14px; }}
 @media print {{ .noprint {{ display:none; }} }}
</style></head><body>
<div class="noprint"><button onclick="window.print()">🖨️ Print / Save as PDF</button></div>
<h1>{e(INSTITUTION_NAME)} <span class="bn">/ প্রভু জগদ্বন্ধু কলেজ</span></h1>
<div class="addr">{e(INSTITUTION_ADDRESS)}</div>
<h2>Department of {e(dept)}{(" / " + e(bn_dept) + " বিভাগ") if bn_dept else ""}</h2>
<h2 class="t">OFFICIAL REPORT CARD <span class="bn">/ অফিসিয়াল রিপোর্ট কার্ড</span></h2>
<table class="info">{info_rows}</table>
<h3>{lab("Marks Statement", "নম্বরের বিবরণ")}</h3>
<table class="m"><tr><th>{lab("Q.No", "প্রশ্ন নং")}</th><th>{lab("Question / Topic", "প্রশ্ন / বিষয়")}</th><th>{lab("Type", "ধরন")}</th>
<th>{lab("Max", "পূর্ণমান")}</th><th>{lab("Awarded", "প্রাপ্ত")}</th><th>{lab("Faculty Remark", "শিক্ষকের মন্তব্য")}</th></tr>{rows}</table>
<table class="sum"><tr><td><b>{lab("Total", "মোট")}</b><br>{t['obtained']:g} / {t['max']:g}</td>
<td><b>{lab("Percentage", "শতকরা")}</b><br>{t['percent']:.2f}%</td>
<td><b>{lab("Grade", "গ্রেড")}</b><br>{e(t['grade'])} ({e(t['grade_desc'])})</td>
<td><b>{lab("Result", "ফলাফল")}</b><br>{result}</td></tr></table>
{feedback}
<div class="sig"><div>{lab("Evaluator's Signature", "মূল্যায়নকারীর স্বাক্ষর")}</div><div>{lab("Head of Department", "বিভাগীয় প্রধান")}</div></div>
<div class="foot">This is a computer-generated report card issued after faculty evaluation was finalised.<br>
এটি শিক্ষকের মূল্যায়ন চূড়ান্ত হওয়ার পর কম্পিউটার-উৎপন্ন রিপোর্ট কার্ড।</div>
</body></html>"""


# ======================================================================
# THEME — Visual theme: neon CSS, floating 3D cubes and the Three.js hero banner.
# ======================================================================
NEON_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@600;800&family=Poppins:wght@300;400;600&family=Noto+Sans+Bengali:wght@400;600;700&display=swap');

:root{
  --c1:#ff2e97; --c2:#7b2ff7; --c3:#00e5ff; --c4:#ffd400; --c5:#00ff9d;
}

/* ---------- Animated gradient backdrop ---------- */
.stApp{
  background: linear-gradient(135deg,#0b0420,#1a0638,#05172e,#2a0845,#031c2e);
  background-size: 400% 400%;
  animation: bgShift 22s ease infinite;
  font-family:'Poppins','Noto Sans Bengali',sans-serif;
}
@keyframes bgShift{0%{background-position:0% 50%}50%{background-position:100% 50%}100%{background-position:0% 50%}}
[data-testid="stHeader"]{background:transparent;}
.block-container{position:relative;z-index:2;padding-top:1.5rem;}

/* ---------- Floating 3D cubes in background ---------- */
.scene3d{position:fixed;inset:0;perspective:900px;z-index:0;pointer-events:none;overflow:hidden;}
[data-testid="stFileUploader"] [data-testid="stFileChip"] button,[data-testid="stFileUploader"] [data-testid="stFileUploaderFile"] button,
[data-testid="stFileUploaderDeleteBtn"] button{background:rgba(255,46,151,.45) !important;box-shadow:none !important;
  border-radius:50% !important;min-width:26px;min-height:26px;padding:0 !important;}
[data-testid="stFileUploader"] [data-testid="stFileChip"] button *,[data-testid="stFileUploaderDeleteBtn"] button *{color:#fff !important;}
[data-testid="stFileUploader"] [data-testid="stFileChip"] button svg,[data-testid="stFileUploader"] [data-testid="stFileChip"] button svg *,
[data-testid="stFileUploaderDeleteBtn"] button svg,[data-testid="stFileUploaderDeleteBtn"] button svg *{fill:none !important;stroke:#fff !important;stroke-width:2.2;}
.cube{position:absolute;width:60px;height:60px;transform-style:preserve-3d;
      animation:spin 14s linear infinite, floaty 9s ease-in-out infinite;}
.cube div{position:absolute;width:60px;height:60px;border:2px solid;opacity:.55;
          box-shadow:0 0 18px currentColor, inset 0 0 18px currentColor;}
.cube div:nth-child(1){transform:translateZ(30px)}
.cube div:nth-child(2){transform:rotateY(90deg) translateZ(30px)}
.cube div:nth-child(3){transform:rotateY(180deg) translateZ(30px)}
.cube div:nth-child(4){transform:rotateY(-90deg) translateZ(30px)}
.cube div:nth-child(5){transform:rotateX(90deg) translateZ(30px)}
.cube div:nth-child(6){transform:rotateX(-90deg) translateZ(30px)}
.cube.a{left:6%;top:18%;color:var(--c1);animation-duration:12s,8s}
.cube.b{left:88%;top:12%;color:var(--c3);animation-duration:17s,10s;transform:scale(1.5)}
.cube.c{left:80%;top:68%;color:var(--c4);animation-duration:15s,7s}
.cube.d{left:10%;top:72%;color:var(--c5);animation-duration:20s,11s;transform:scale(1.8)}
.cube.e{left:50%;top:88%;color:var(--c2);animation-duration:13s,9s}
.cube div{border-color:currentColor;}
@keyframes spin{from{transform:rotateX(0) rotateY(0) rotateZ(0)}to{transform:rotateX(360deg) rotateY(720deg) rotateZ(360deg)}}
@keyframes floaty{0%,100%{margin-top:0}50%{margin-top:-50px}}

/* ---------- Typography ---------- */
h1,h2,h3,h4,h5{font-family:'Orbitron','Noto Sans Bengali',sans-serif !important;letter-spacing:.5px;}
h1{
  background:linear-gradient(90deg,var(--c1),var(--c4),var(--c3),var(--c1));
  background-size:300% auto;-webkit-background-clip:text;background-clip:text;
  -webkit-text-fill-color:transparent;animation:shine 6s linear infinite;
  text-shadow:0 0 30px rgba(255,46,151,.35);
}
@keyframes shine{to{background-position:300% center}}
h2,h3{color:var(--c3) !important;text-shadow:0 0 14px rgba(0,229,255,.55);}
h4{color:#ffb3e1 !important;text-shadow:0 0 10px rgba(255,46,151,.5);}
p,li,label,span,.stMarkdown,[data-testid="stWidgetLabel"] p,[data-testid="stCaptionContainer"]{color:#e9e4ff;}
hr{border:none !important;height:2px !important;
   background:linear-gradient(90deg,transparent,var(--c1),var(--c3),var(--c4),transparent) !important;
   box-shadow:0 0 12px var(--c1);}

/* ---------- Tabs ---------- */
.stTabs [data-baseweb="tab-list"]{gap:10px;background:rgba(255,255,255,.04);padding:8px;border-radius:16px;
  border:1px solid rgba(255,255,255,.12);backdrop-filter:blur(10px);}
.stTabs [data-baseweb="tab"]{border-radius:12px;padding:10px 18px;color:#cfc4ff;
  transition:all .3s;transform-style:preserve-3d;}
.stTabs [data-baseweb="tab"]:hover{transform:translateY(-4px) rotateX(12deg);color:#fff;
  background:rgba(123,47,247,.35);box-shadow:0 8px 20px rgba(123,47,247,.5);}
.stTabs [aria-selected="true"]{background:linear-gradient(135deg,var(--c1),var(--c2)) !important;
  color:#fff !important;box-shadow:0 0 22px rgba(255,46,151,.7);}
.stTabs [data-baseweb="tab-highlight"],.stTabs [data-baseweb="tab-border"]{display:none;}

/* ---------- Inputs (glass) ---------- */
/* wrappers must be dark too, otherwise white text sits on a white box */
[data-baseweb="input"],[data-baseweb="base-input"],[data-baseweb="textarea"],
.stTextInput>div>div,.stTextArea>div>div,.stNumberInput>div>div{
  background:#1b0a3d !important;border-radius:12px !important;}
.stTextInput input,.stTextArea textarea,.stNumberInput input,
[data-baseweb="input"] input,[data-baseweb="textarea"] textarea,[data-baseweb="base-input"] input,
[data-baseweb="select"] *{
  background:#1b0a3d !important;color:#ffffff !important;-webkit-text-fill-color:#ffffff !important;
  caret-color:#00e5ff !important;}
.stTextInput input::placeholder,.stTextArea textarea::placeholder,.stNumberInput input::placeholder{
  color:#9d8fd1 !important;-webkit-text-fill-color:#9d8fd1 !important;opacity:1 !important;}
.stNumberInput button{background:#2a1260 !important;color:#fff !important;}
.stTextInput input,.stTextArea textarea,.stNumberInput input,[data-baseweb="select"]>div{
  background:#1b0a3d !important;color:#fff !important;
  border:1px solid rgba(0,229,255,.35) !important;border-radius:12px !important;
  backdrop-filter:blur(8px);transition:all .3s;}
.stTextInput input:focus,.stTextArea textarea:focus,.stNumberInput input:focus{
  border-color:var(--c1) !important;box-shadow:0 0 0 2px rgba(255,46,151,.45),0 0 25px rgba(255,46,151,.45) !important;
  transform:translateY(-2px);}
[data-baseweb="popover"] ul{background:#1a0638 !important;}
[data-baseweb="popover"] li{color:#fff !important;}
[data-testid="stFileUploader"] section{background:rgba(255,255,255,.05);border:2px dashed var(--c3);
  border-radius:16px;transition:all .3s;}
[data-testid="stFileUploader"] section:hover{border-color:var(--c1);box-shadow:0 0 25px rgba(255,46,151,.5);
  transform:perspective(600px) rotateX(3deg) scale(1.01);}
[data-testid="stFileUploader"] section *{color:#e9e4ff !important;}
/* Upload / Browse button inside the uploader */
[data-testid="stFileUploader"] button,
[data-testid="stFileUploaderDropzone"] button{
  background:linear-gradient(135deg,#ff2e97,#7b2ff7) !important;
  border:none !important;border-radius:12px !important;
  box-shadow:0 5px 0 #4a1a8f,0 8px 20px rgba(123,47,247,.5) !important;transition:all .25s;}
[data-testid="stFileUploader"] button *,
[data-testid="stFileUploaderDropzone"] button *{color:#ffffff !important;fill:#ffffff !important;
  -webkit-text-fill-color:#ffffff !important;font-weight:600;}
[data-testid="stFileUploader"] button:hover,
[data-testid="stFileUploaderDropzone"] button:hover{
  transform:translateY(-3px);box-shadow:0 8px 0 #4a1a8f,0 14px 26px rgba(255,46,151,.6) !important;}
/* uploaded file name rows + delete (x) button */
[data-testid="stFileUploaderFile"],[data-testid="stFileChip"]{
  background:rgba(27,10,61,.9) !important;border-radius:12px;border:1px solid rgba(0,229,255,.4);}
[data-testid="stFileUploaderFile"] *,[data-testid="stFileChip"] *{color:#ffffff !important;}
[data-testid="stFileUploaderDeleteBtn"] button{background:transparent !important;box-shadow:none !important;}

/* ---------- Radio options as 3D cards ---------- */
.stRadio [role="radiogroup"] label{background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.15);
  border-radius:14px;padding:10px 16px;margin-bottom:8px;transition:all .25s;transform-style:preserve-3d;}
.stRadio [role="radiogroup"] label:hover{transform:perspective(600px) translateZ(14px) rotateY(-4deg) translateX(6px);
  background:linear-gradient(90deg,rgba(255,46,151,.3),rgba(0,229,255,.25));
  box-shadow:0 10px 25px rgba(0,229,255,.35);border-color:var(--c3);}

/* ---------- Buttons ---------- */
.stButton>button,.stFormSubmitButton>button,.stDownloadButton>button{
  background:linear-gradient(135deg,var(--c1),var(--c2),var(--c3));background-size:250% 250%;
  color:#fff !important;font-weight:600;border:none;border-radius:14px;padding:.7rem 1rem;
  box-shadow:0 8px 0 #4a1a8f,0 14px 30px rgba(123,47,247,.55);
  transition:all .25s;animation:btnflow 5s ease infinite;}
@keyframes btnflow{0%{background-position:0% 50%}50%{background-position:100% 50%}100%{background-position:0% 50%}}
.stButton>button:hover,.stFormSubmitButton>button:hover,.stDownloadButton>button:hover{
  transform:translateY(-4px) scale(1.02);box-shadow:0 12px 0 #4a1a8f,0 22px 40px rgba(255,46,151,.6);color:#fff !important;}
.stButton>button:active,.stFormSubmitButton>button:active{transform:translateY(6px);box-shadow:0 2px 0 #4a1a8f,0 4px 12px rgba(0,0,0,.5);}
.stButton>button[kind="primary"]{background:linear-gradient(135deg,var(--c4),var(--c1),var(--c2));
  box-shadow:0 8px 0 #8a1450,0 14px 34px rgba(255,46,151,.65);animation:btnflow 4s ease infinite, pulse 2.2s infinite;}
@keyframes pulse{0%,100%{filter:brightness(1)}50%{filter:brightness(1.25)}}

/* ---------- Metrics as tilted 3D cards ---------- */
[data-testid="stMetric"]{background:linear-gradient(145deg,rgba(123,47,247,.35),rgba(0,229,255,.18));
  border:1px solid rgba(255,255,255,.25);border-radius:18px;padding:16px 18px;
  transform:perspective(800px) rotateX(6deg) rotateY(-6deg);transition:all .4s;
  box-shadow:0 18px 35px rgba(0,0,0,.5),0 0 25px rgba(123,47,247,.45);}
[data-testid="stMetric"]:hover{transform:perspective(800px) rotateX(0) rotateY(0) translateY(-8px) scale(1.04);
  box-shadow:0 26px 45px rgba(0,0,0,.55),0 0 40px rgba(0,229,255,.7);}
[data-testid="stMetricValue"]{color:var(--c4) !important;text-shadow:0 0 14px rgba(255,212,0,.7);
  font-family:'Orbitron',sans-serif;}
[data-testid="stMetricLabel"] *{color:#bfe9ff !important;}

/* ---------- Alerts ---------- */
[data-testid="stAlert"]{border-radius:16px;backdrop-filter:blur(10px);border:1px solid rgba(255,255,255,.2);
  animation:slideIn .6s ease both;}
@keyframes slideIn{from{opacity:0;transform:translateX(-40px) rotateY(25deg)}to{opacity:1;transform:none}}
[data-testid="stAlert"] *{color:#fff !important;}
/* dark tinted alert boxes so white text is readable */
[data-testid="stAlert"],[data-testid="stAlert"]>div,[data-testid="stAlert"] [data-baseweb="notification"]{
  background:rgba(27,10,61,.92) !important;border:1px solid rgba(0,229,255,.55) !important;
  border-left:6px solid #00e5ff !important;box-shadow:0 0 20px rgba(0,229,255,.3);}
[data-testid="stAlert"]:has([data-testid="stAlertContentSuccess"]),
[data-testid="stAlert"]:has([data-testid="stAlertContentSuccess"])>div{
  background:rgba(0,70,45,.9) !important;border-color:#00ff9d !important;box-shadow:0 0 20px rgba(0,255,157,.35);}
[data-testid="stAlert"]:has([data-testid="stAlertContentWarning"]),
[data-testid="stAlert"]:has([data-testid="stAlertContentWarning"])>div{
  background:rgba(90,65,0,.9) !important;border-color:#ffd400 !important;box-shadow:0 0 20px rgba(255,212,0,.35);}
[data-testid="stAlert"]:has([data-testid="stAlertContentError"]),
[data-testid="stAlert"]:has([data-testid="stAlertContentError"])>div{
  background:rgba(95,10,45,.92) !important;border-color:#ff2e97 !important;box-shadow:0 0 20px rgba(255,46,151,.4);}
[data-testid="stAlert"] ::selection{background:#ff2e97;color:#fff;}

/* ---------- Forms & expanders ---------- */
[data-testid="stForm"]{background:rgba(255,255,255,.04);border:1px solid rgba(255,46,151,.4);
  border-radius:20px;box-shadow:0 0 30px rgba(255,46,151,.25);}
</style>

<div class="scene3d">
  <div class="cube a"><div></div><div></div><div></div><div></div><div></div><div></div></div>
  <div class="cube b"><div></div><div></div><div></div><div></div><div></div><div></div></div>
  <div class="cube c"><div></div><div></div><div></div><div></div><div></div><div></div></div>
  <div class="cube d"><div></div><div></div><div></div><div></div><div></div><div></div></div>
  <div class="cube e"><div></div><div></div><div></div><div></div><div></div><div></div></div>
</div>
"""

EXTRA_CSS = """
<style>
/* ---------- v2 additions: sidebar, expanders, tables, code, progress ---------- */
[data-testid="stSidebar"]{background:linear-gradient(180deg,#14072e,#0a1030 60%,#1a0638);
  border-right:1px solid rgba(0,229,255,.35);box-shadow:0 0 30px rgba(123,47,247,.4);}
[data-testid="stSidebar"] *{color:#e9e4ff;}
[data-testid="stSidebar"] .stRadio [role="radiogroup"] label{padding:8px 12px;margin-bottom:6px;}
[data-testid="stSidebar"] .stRadio [role="radiogroup"] label:hover{transform:perspective(600px) translateZ(8px) translateX(5px);}
[data-testid="stExpander"]{background:rgba(255,255,255,.05);border:1px solid rgba(0,229,255,.3) !important;
  border-radius:16px;overflow:hidden;}
[data-testid="stExpander"] summary,[data-testid="stExpander"] summary *{color:#fff !important;}
pre,code{background:#120628 !important;color:#7dffcf !important;border-radius:10px;}
[data-testid="stCode"] pre{border:1px solid rgba(0,255,157,.35);}
[data-testid="stProgress"]>div>div{background:rgba(255,255,255,.12) !important;}
[data-testid="stProgress"] div[role="progressbar"]>div{background:linear-gradient(90deg,#ff2e97,#ffd400,#00ff9d) !important;}
[data-testid="stDataFrame"]{border:1px solid rgba(0,229,255,.4);border-radius:14px;overflow:hidden;
  box-shadow:0 0 22px rgba(0,229,255,.25);}
[data-testid="stCheckbox"] label span{color:#e9e4ff !important;}
.stSelectbox [data-baseweb="select"] *{color:#fff !important;}
[data-testid="stVerticalBlockBorderWrapper"]{border-color:rgba(0,229,255,.35) !important;border-radius:16px;}
.pin-card{margin:14px 0;padding:22px;border-radius:20px;text-align:center;
  background:linear-gradient(135deg,rgba(255,212,0,.25),rgba(255,46,151,.3),rgba(123,47,247,.35));
  border:2px solid #ffd400;box-shadow:0 0 40px rgba(255,212,0,.5);
  transform:perspective(900px) rotateX(5deg);}
.pin-card .pin{font-family:Orbitron,sans-serif;font-size:2.6rem;letter-spacing:12px;color:#fff;
  text-shadow:0 0 22px #ffd400;}
.dept-card{padding:26px;border-radius:22px;margin:10px 0 18px;
  background:linear-gradient(135deg,rgba(255,46,151,.28),rgba(123,47,247,.32),rgba(0,229,255,.25));
  border:1px solid rgba(255,255,255,.3);box-shadow:0 18px 45px rgba(123,47,247,.5);
  transform:perspective(1000px) rotateX(3deg);}
.role-chip{display:inline-block;padding:3px 12px;border-radius:999px;font-size:.8rem;font-weight:600;
  background:linear-gradient(90deg,#00ff9d,#00e5ff);color:#06122a !important;}
.role-chip.student{background:linear-gradient(90deg,#ffd400,#ff2e97);}

/* ---------- v3 fixes: metric numbers, expander headers, charts, Bengali font ---------- */
[data-testid="stMetricValue"],[data-testid="stMetricValue"] *{font-size:1.6rem !important;white-space:normal !important;
  overflow:visible !important;text-overflow:clip !important;line-height:1.2 !important;}
[data-testid="stMetric"]{overflow:visible !important;}
[data-testid="stExpander"] summary,[data-testid="stExpander"] details>summary{background:rgba(27,10,61,.95) !important;border-radius:14px;}
[data-testid="stExpander"] details{background:transparent !important;}
[data-testid="stVegaLiteChart"],[data-testid="stArrowVegaLiteChart"]{background:#ffffff;border-radius:14px;padding:10px;
  box-shadow:0 0 25px rgba(0,229,255,.28);overflow:hidden;}
</style>
"""

THREE_HERO = """
<div id="wrap" style="width:100%;height:100%;position:relative;font-family:sans-serif;">
  <canvas id="c" style="width:100%;height:100%;display:block;"></canvas>
  <div style="position:absolute;left:0;right:0;bottom:8px;text-align:center;color:#fff;
       font-size:13px;letter-spacing:4px;text-shadow:0 0 12px #00e5ff;">
       MOVE YOUR MOUSE · EXPLORE THE BRIDGE
  </div>
</div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
<script>
const canvas=document.getElementById('c');
const renderer=new THREE.WebGLRenderer({canvas,alpha:true,antialias:true});
renderer.setPixelRatio(Math.min(window.devicePixelRatio,2));
const scene=new THREE.Scene();
const camera=new THREE.PerspectiveCamera(55,2,0.1,100);camera.position.z=7;

const knot=new THREE.Mesh(new THREE.TorusKnotGeometry(1.3,0.4,180,24),
  new THREE.MeshStandardMaterial({color:0xff2e97,metalness:.7,roughness:.2,emissive:0x330022}));
scene.add(knot);
const wire=new THREE.Mesh(new THREE.IcosahedronGeometry(2.6,1),
  new THREE.MeshBasicMaterial({color:0x00e5ff,wireframe:true,transparent:true,opacity:.35}));
scene.add(wire);
const ring=new THREE.Mesh(new THREE.TorusGeometry(3.4,0.03,16,120),
  new THREE.MeshBasicMaterial({color:0xffd400}));
ring.rotation.x=Math.PI/2.4;scene.add(ring);
const ring2=ring.clone();ring2.material=new THREE.MeshBasicMaterial({color:0x7b2ff7});
ring2.rotation.x=-Math.PI/3;ring2.rotation.y=.6;scene.add(ring2);

// orbiting colourful spheres
const orbs=[];const cols=[0x00ff9d,0xffd400,0x00e5ff,0xff2e97,0x7b2ff7];
cols.forEach((c,i)=>{
  const m=new THREE.Mesh(new THREE.SphereGeometry(.22,24,24),
    new THREE.MeshStandardMaterial({color:c,emissive:c,emissiveIntensity:.6}));
  m.userData={r:3+i*.25,s:.6+i*.15,o:i*1.3};scene.add(m);orbs.push(m);
});

// particles
const N=900,pos=new Float32Array(N*3),col=new Float32Array(N*3);
for(let i=0;i<N;i++){
  pos[i*3]=(Math.random()-.5)*26;pos[i*3+1]=(Math.random()-.5)*14;pos[i*3+2]=(Math.random()-.5)*14;
  const k=new THREE.Color().setHSL(Math.random(),1,.6);col.set([k.r,k.g,k.b],i*3);
}
const g=new THREE.BufferGeometry();
g.setAttribute('position',new THREE.BufferAttribute(pos,3));
g.setAttribute('color',new THREE.BufferAttribute(col,3));
const pts=new THREE.Points(g,new THREE.PointsMaterial({size:.07,vertexColors:true}));
scene.add(pts);

scene.add(new THREE.AmbientLight(0xffffff,.5));
const l1=new THREE.PointLight(0x00e5ff,2,30);l1.position.set(5,4,5);scene.add(l1);
const l2=new THREE.PointLight(0xff2e97,2,30);l2.position.set(-5,-3,4);scene.add(l2);

let mx=0,my=0;
window.addEventListener('mousemove',e=>{mx=(e.clientX/innerWidth-.5)*2;my=(e.clientY/innerHeight-.5)*2;});
function resize(){const w=canvas.clientWidth,h=canvas.clientHeight;renderer.setSize(w,h,false);
  camera.aspect=w/h;camera.updateProjectionMatrix();}
window.addEventListener('resize',resize);resize();

const clock=new THREE.Clock();
(function loop(){
  const t=clock.getElapsedTime();
  knot.rotation.x=t*.5+my*.6;knot.rotation.y=t*.7+mx*.8;
  const s=1+Math.sin(t*2)*.05;knot.scale.set(s,s,s);
  wire.rotation.y=-t*.25;wire.rotation.x=t*.15;
  ring.rotation.z=t*.6;ring2.rotation.z=-t*.4;
  orbs.forEach(o=>{const d=o.userData;o.position.set(Math.cos(t*d.s+d.o)*d.r,Math.sin(t*d.s*1.3+d.o)*1.6,Math.sin(t*d.s+d.o)*d.r);});
  pts.rotation.y=t*.03;
  camera.position.x+=(mx*1.5-camera.position.x)*.05;
  camera.position.y+=(-my*1-camera.position.y)*.05;camera.lookAt(0,0,0);
  l1.color.setHSL((t*.05)%1,1,.6);
  renderer.render(scene,camera);requestAnimationFrame(loop);
})();
</script>
"""


# ======================================================================
# VIEWS/HOME — Landing page: department selection.
# ======================================================================
def _enter():
    choice = st.session_state.get(f"dept_choice_{lang()}")
    if choice != st.session_state.get("dept"):
        for k in ("stu_step", "stu_draft", "stu_primed", "stu_result"):
            st.session_state.pop(k, None)
    st.session_state["dept"] = choice
    goto(P_TAKE)


def render_home():
    render_hero(320)
    st.title(tr("🎓 Departmental Assessment & Grading Portal"))
    st.markdown(f"**{tr(INSTITUTION_NAME)}**")
    st.caption(tr(INSTITUTION_ADDRESS))
    st.caption(tr("Use the menu on the left (☰ on phones) to switch language."))
    st.markdown("---")

    st.markdown(tr("<div class='dept-card'><h3 style='margin:0'>🏛️ Select Your Department</h3>"
                "<div style='margin-top:6px'>Pick the department whose assessments and resources you need.</div></div>"),
                unsafe_allow_html=True)
    current = st.session_state.get("dept")
    idx = DEPARTMENTS.index(current) if current in DEPARTMENTS else None
    st.selectbox(
        tr("Choose the academic department whose resources you want to access"),
        DEPARTMENTS, index=idx, placeholder=tr("Select a department…"), key=f"dept_choice_{lang()}", format_func=dname,
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


# ======================================================================
# VIEWS/LOGIN — Faculty / administrator sign-in.
# ======================================================================
def render_login(dept):
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
        ok, msg = login(username, password, dept)
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


# ======================================================================
# VIEWS/ACCOUNT — Password change + sign-out for the logged-in teacher/admin.
# ======================================================================
def render_account(user):
    banner(tr("⚙️ My Account"), trf("Signed in as **{0}** · role: {1}", user['username'], user['role']))
    if "pw_ok" in st.session_state:
        st.success(tr(st.session_state.pop("pw_ok")))
    if user.get("must_change"):
        st.warning(tr("You are using a temporary password. Set a new one to unlock the dashboards."))
    with st.form("pw_form", clear_on_submit=True):
        old = st.text_input(tr("Current password"), type="password")
        new = st.text_input(trf("New password (min {0} chars, letters + digits)", MIN_PASSWORD_LEN), type="password")
        new2 = st.text_input(tr("Repeat new password"), type="password")
        go = st.form_submit_button(tr("🔑 Change Password"), **STRETCH)
    if go:
        if new != new2:
            st.error(tr("The new passwords do not match."))
        else:
            err = change_password(user, old, new)
            if err:
                st.error(tr(err))
            else:
                st.session_state["pw_ok"] = "✅ Password updated. Use the NEW password the next time you sign in."
                st.rerun()
    st.markdown("---")
    if st.button(tr("🚪 Sign Out"), **STRETCH):
        logout()
        goto(P_HOME)
        st.rerun()

GUIDE = {
    "student": [
        "Choose your language — English or বাংলা — at the top of this panel.",
        "On **Home**, select your department and press **Enter Student Portal**.",
        "Sign in with the roll number and PIN given by your teacher. If no class list exists yet, just type your name and roll number.",
        "Open **Take Assessment**, choose a test and press **Start test**. For timed tests the clock starts at once — do not refresh the page.",
        "Answer every question. Upload your handwritten pages or code file where asked, then press **Review My Answers**.",
        "Check your answers, edit anything you want, tick the confirmation box and press **Final Submit**. Save your Submission ID and PIN if they are shown.",
        "When your teacher finishes marking, open **My Report Card** to see your marks and download your report card.",
        "Open **Study Materials** any time to download your department's syllabus, notes and question papers.",
    ],
    "teacher": [
        "Select your department on **Home**, open **Faculty Login** and sign in with the username and temporary password from the administrator. Choose a new password when asked.",
        "**Question Creator:** add questions with a number, marks, type and answer key — or import them from a PDF.",
        "**Students:** import your class list (CSV) and download the PIN sheet — PINs are shown only once.",
        "**Tests:** create a test — choose its questions, opening and closing time, time limit and negative marking — and publish it.",
        "**Upload Materials:** put the syllabus, notes and question papers in your department's folders.",
        "**Evaluation:** open each submission, give marks and remarks to written and code answers, then press **Finalise** to create the report card.",
        "**Analytics:** see averages, score distribution, weak questions and test comparison, and download the results as CSV.",
        "Sign out from **Account** when you finish, especially on a shared computer.",
    ],
    "admin": [
        "Open **Faculty Login** and sign in as `admin`; set a new permanent password.",
        "In **Admin Console → Faculty Accounts**, choose a department first, then create each teacher's username and temporary password.",
        "Use **Reset password** if a teacher forgets theirs, and **Delete account** when someone leaves.",
        "In **Storage & Backup**, press **Test connection** after any setup change and **Back up now** before big changes. Restore only when really needed.",
        "Check the **Audit Log** now and then for failed sign-ins and other security events.",
        "Remove inappropriate entries from **Reviews**.",
    ],
}
ROLE_LABELS = {"student": "Student", "teacher": "Teacher", "admin": "Administrator"}

def sidebar_guide(user, dept):
    default = "admin" if user and user["role"] == "admin" else "teacher" if user else "student"
    with st.expander(tr("📖 How to use this portal — step by step")):
        who = st.selectbox(tr("I am a…"), list(ROLE_LABELS), index=list(ROLE_LABELS).index(default),
                           format_func=lambda r: tr(ROLE_LABELS[r]), key=f"guide_who_{lang()}_{default}")
        st.markdown("\n".join(f"{i}. {tr(step)}" for i, step in enumerate(GUIDE[who], 1)))
        st.caption(tr("More answers are in ❓ FAQ."))

FAQ = [
    ("🎓 Students", [
        ("I forgot my PIN. What should I do?", "Ask your teacher to open **Students**, select your name and press **Generate new PIN**. Your old PIN stops working."),
        ("What happens if I refresh the page during a test?", "Answers you have not submitted are lost, but the test clock keeps running. Sign in again and press **Resume test**. Avoid refreshing and keep your internet on."),
        ("What if the time ends while I am writing?", "Your answers are submitted automatically and marked as auto-submitted. If the page could not react immediately, the submission is also marked late and your teacher decides what to do."),
        ("Can I take a test twice?", "No — each test allows one attempt per student. If something went wrong, ask your teacher; they can remove your submission so you can try again."),
        ("Why can't I see the test I am looking for?", "A test appears only after the teacher publishes it. It can also be **not open yet** or **closed** — the dates are shown on the test card (Indian time)."),
        ("Where can I find my marks and report card?", "Under **My Report Card**, after your teacher has finalised the evaluation. Until then it shows that evaluation is pending."),
        ("My name is in Bengali. Which report card should I download?", "Use the **Printable report card (HTML)**: open it and choose Print → Save as PDF. It shows Bengali letters correctly; the plain PDF may not."),
        ("Which files can I upload with my answers?", "Handwritten answers: PDF, PNG or JPG. Code: .py or .txt files. Each file can be up to 10 MB. Uploaded code is only stored for your teacher — it is never run."),
        ("How does negative marking work?", "If a test has negative marking, a wrong MCQ answer loses a fraction of that question's marks (shown on the test card). Unanswered questions lose nothing, and your total never goes below zero."),
        ("I cannot find my department's study materials.", "Select the right department on **Home** first. Materials are kept separately for each department; if the folder is empty, your teacher has not uploaded anything yet."),
    ]),
    ("👨‍🏫 Teachers", [
        ("I forgot my password.", "Ask the administrator to reset it in **Admin Console → Faculty Accounts**. You will get a temporary password and must choose a new one at your next login."),
        ("How do I let a student retake a test?", "Open **Evaluation**, choose the student's submission and use **Delete submission** in the danger zone. The student's attempt is cleared too, so they can start again."),
        ("How do I switch student login on or off?", "Import a class list in **Students** to switch roll-number + PIN login on. Removing the whole roster switches back to anonymous mode, where students type their own name and roll."),
        ("Does the time limit work without a class list?", "Not reliably: without a class list the clock starts in the student's browser and a refresh can restart it. Import a class list to enforce time limits."),
        ("What happens to submissions if I edit or delete a question or test?", "Nothing — every submission keeps its own copy of the paper, so marks and report cards stay correct."),
        ("Can I upload large video lectures?", "Study materials accept PDF, Word, PowerPoint, Excel, text, images and ZIP up to 25 MB per file. For videos, upload a document that contains the link."),
    ]),
    ("🛡️ Administrators", [
        ("I forgot the admin password.", "Put a new value for `ADMIN_RESET_PASSWORD` in Streamlit Secrets, save, and sign in with it; then choose a new password."),
        ("Is the data safe? Where is it stored?", "Records and files are stored in your Supabase project. Passwords and PINs are stored in scrambled form, sign-ins are locked after repeated mistakes, and automatic backups are kept. Download a backup now and then for extra safety."),
        ("How does backups and restore work?", "A backup is made automatically when the app is used and the last one is over 24 hours old; the latest 15 are kept. Restoring replaces all records with the backup (after taking a safety copy) and needs you to type RESTORE."),
    ]),
]

def render_faq():
    banner(tr("❓ Frequently Asked Questions"), tr("Quick answers for students, teachers and administrators"))
    q = st.text_input(tr("Search the questions"), key=f"faq_q_{lang()}").strip().lower()
    shown = 0
    for title, items in FAQ:
        rows = [(tr(a), tr(b)) for a, b in items if not q or q in tr(a).lower() or q in tr(b).lower()]
        if not rows:
            continue
        st.markdown(f"#### {tr(title)}")
        for question, answer in rows:
            with st.expander(question):
                st.markdown(answer)
            shown += 1
    if not shown:
        st.info(tr("No question matches your search."))
    st.caption(tr("Still stuck? Please ask your department teacher, or write a review with your question."))

REVIEW_ROLES = {"student": "Student", "teacher": "Teacher", "other": "Parent / Other"}
REVIEW_COOLDOWN = 600
_MD_SPECIAL = re.compile(r"([\\`*_\[\]()#!|~$<>&])")

def _plain(text):
    return _MD_SPECIAL.sub(r"\\\1", text).replace("\n", "  \n")

def render_reviews(user):
    banner(tr("⭐ Reviews & Feedback"), tr("Share your experience with the portal — your review helps us improve it"))
    try:
        reviews = list_reviews()
    except StorageError as e:
        st.error(str(e))
        return
    if reviews:
        total = len(reviews)
        avg = sum(r["rating"] for _, r in reviews) / total
        c1, c2 = st.columns(2)
        c1.metric(tr("Average rating"), f"{avg:.1f} / 5")
        c2.metric(tr("Total reviews"), total)
        for n in range(5, 0, -1):
            cnt = sum(1 for _, r in reviews if r["rating"] == n)
            a, b, c = st.columns([1, 6, 1])
            a.markdown(f"{n} ⭐")
            b.progress(cnt / total)
            c.markdown(str(cnt))
    else:
        st.info(tr("No reviews yet — be the first to write one!"))

    st.markdown(tr("#### ✍️ Write a review"))
    ver = ss.setdefault("rv_ver", 0)
    with st.form(f"review_form_{ver}"):
        a, b = st.columns(2)
        name = a.text_input(tr("Your name (optional)"), max_chars=60)
        role = b.selectbox(tr("I am a…"), list(REVIEW_ROLES), format_func=lambda r: tr(REVIEW_ROLES[r]), key=f"rv_role_{lang()}_{ver}")
        c, d = st.columns(2)
        dept_opts = [""] + DEPARTMENTS
        dept_sel = c.selectbox(tr("Department (optional)"), dept_opts, key=f"rv_dept_{lang()}_{ver}",
                               format_func=lambda x: tr("Not specified") if not x else dname(x))
        rating = d.radio(tr("Your rating"), [5, 4, 3, 2, 1], horizontal=True, format_func=lambda n: "⭐" * n, key=f"rv_rating_{ver}")
        comment = st.text_area(tr("Your review"), max_chars=600, placeholder=tr("What worked well? What can be improved?"))
        send = st.form_submit_button(tr("📨 Submit review"), **STRETCH)
    st.caption(tr("Maximum 600 characters. Please be respectful — reviews are public."))
    if send:
        wait = REVIEW_COOLDOWN - (time.time() - ss.get("rv_last", 0))
        if len(comment.strip()) < 5:
            st.error(tr("Please write a short comment (at least 5 characters)."))
        elif wait > 0:
            st.error(tr("Please wait a few minutes before posting another review."))
        else:
            add_review(name, role, dept_sel, rating, comment)
            ss["rv_last"] = time.time()
            ss["rv_ver"] = ver + 1
            ss["rv_thanks"] = True
            st.rerun()
    if ss.pop("rv_thanks", False):
        st.success(tr("Thank you! Your review has been added."))

    if reviews:
        st.markdown("---")
        shown = ss.setdefault("rv_shown", 10)
        admin_view = is_admin(user)
        for key, r in reviews[:shown]:
            who = r["name"] or tr("Anonymous")
            meta = " · ".join(x for x in [tr(REVIEW_ROLES.get(r["role"], "Parent / Other")), dname(r["dept"]) if r["dept"] else "", r["created"][:10]] if x)
            st.markdown(f"{'⭐' * r['rating']}  **{_plain(who)}**")
            st.caption(_plain(meta))
            st.markdown(_plain(r["comment"]))
            st.markdown("<hr style='margin:6px 0;opacity:.25'>", unsafe_allow_html=True)
            if admin_view and st.button(tr("🗑️ Delete review"), key=f"rvdel_{key}"):
                delete_review(key)
                st.success(tr("Review deleted."))
                st.rerun()
        if len(reviews) > shown and st.button(tr("Show more reviews"), **STRETCH):
            ss["rv_shown"] = shown + 10
            st.rerun()
# ======================================================================
# VIEWS/ADMIN — Administrator console: teacher credentials per department, audit log.
# ======================================================================
def render_admin(user):
    banner(tr("🛡️ Administrator Console"), tr("Manage departmental faculty credentials"))
    t_accounts, t_audit, t_storage = st.tabs([tr("👥 Faculty Accounts"), tr("🧾 Audit Log"), tr("🗄️ Storage & Backup")])

    with t_accounts:
        dept = st.selectbox(tr("Department"), DEPARTMENTS, key=f"adm_dept_{lang()}", format_func=dname)
        teachers = list_teachers(dept)
        st.markdown(trf("**Faculty accounts in {0}:** {1}", dept, ", ".join(f"`{t}`" for t in teachers) or tr("none yet")))

        st.markdown(tr("#### ➕ Create faculty account"))
        with st.form(f"add_t_{dept}", clear_on_submit=True):
            u = st.text_input(tr("Username"))
            p = st.text_input(tr("Temporary password"), type="password",
                              help=tr("The teacher must change it at first login."))
            if st.form_submit_button(tr("Create account"), **STRETCH):
                err = add_teacher(dept, u, p)
                st.error(tr(err)) if err else st.success(trf("Created `{0}`.", u.strip().lower()))
                if not err:
                    st.rerun()

        if teachers:
            st.markdown(tr("#### 🔄 Reset password / remove"))
            who = st.selectbox(tr("Account"), teachers, key=f"adm_who_{dept}")
            with st.form(f"reset_{dept}_{who}", clear_on_submit=True):
                newp = st.text_input(tr("New temporary password"), type="password")
                c1, c2 = st.columns(2)
                reset = c1.form_submit_button(tr("Reset password"), **STRETCH)
                remove = c2.form_submit_button(tr("🗑️ Delete account"), **STRETCH)
            if reset:
                err = reset_teacher_password(dept, who, newp)
                st.error(tr(err)) if err else st.success(tr("Password reset; teacher must change it at next login."))
            if remove:
                delete_teacher(dept, who)
                st.rerun()

    with t_audit:
        st.caption(tr("Most recent security events first (logins, failures, lockouts, password changes, finalised evaluations)."))
        lines = read_audit(80)
        st.code("\n".join(lines) if lines else "No events yet.", language="text")

    with t_storage:
        be = backend()
        if be.persistent:
            st.success(trf("Storage backend: **{0}** — data survives restarts.", be.name))
        else:
            st.warning(tr("Storage backend: **local disk**. On Streamlit Cloud this is erased whenever the app restarts. "
                       "Add SUPABASE_URL and SUPABASE_SERVICE_KEY to Secrets to make data permanent."))
        if st.button(tr("🔌 Test / initialise storage connection"), **STRETCH):
            try:
                ok, msg = be.check()
            except StorageError as e:
                ok, msg = False, str(e)
            (st.success if ok else st.error)(msg)
        with st.expander(tr("One-time Supabase setup SQL (SQL Editor → New query → Run)")):
            st.code(SETUP_SQL, language="sql")
        st.markdown(tr("##### 💾 Backup"))
        st.caption(tr("Exports all records (accounts, questions, submissions, marks, audit log) as one JSON file. "
                   "Uploaded files and report PDFs are not included — keep that file somewhere safe and export regularly."))
        if st.button(tr("Prepare backup file"), **STRETCH):
            st.session_state["backup_blob"] = json.dumps(be.all_docs(), indent=2, ensure_ascii=False).encode("utf-8")
        if "backup_blob" in st.session_state:
            st.download_button(tr("📥 Download backup (JSON)"), st.session_state["backup_blob"],
                               file_name=f"portal_backup_{datetime.now():%Y%m%d_%H%M}.json", mime="application/json", **STRETCH)

        st.markdown("---")
        st.markdown(tr("##### 🛟 Automatic backups & restore"))
        st.caption(trf("A backup is made automatically when someone uses the app and the newest one is older than {0} hours. "
                       "The latest {1} are kept. Backups contain all records (not uploaded files).",
                       BACKUP_EVERY_HOURS, KEEP_BACKUPS))
        try:
            backups = list_backups()
        except StorageError as e:
            backups = []
            st.error(str(e))
        if backups:
            st.markdown(trf("Latest backup: **{0}** ({1})", backups[0][1].strftime("%Y-%m-%d %H:%M"), backups[0][2]))
        if st.button(tr("💾 Back up now"), **STRETCH):
            create_backup("manual")
            st.success(tr("Backup created."))
            st.rerun()
        if backups:
            by_key = {k: (dt, kind) for k, dt, kind in backups}
            sel = st.selectbox(tr("Select a backup"), list(by_key), key="bk_sel",
                               format_func=lambda k: f"{by_key[k][0]:%Y-%m-%d %H:%M} · {by_key[k][1]}")
            st.download_button(tr("📥 Download this backup (JSON)"),
                               json.dumps(be.get(sel, {}), ensure_ascii=False).encode("utf-8"),
                               file_name=sel.split("/")[-1] + ".json", mime="application/json", **STRETCH)
            st.warning(tr("Restoring REPLACES all current records (accounts, questions, tests, submissions…) with the backup. "
                          "A safety copy of the current data is made first."))
            word = st.text_input(tr("Type RESTORE to confirm"), key="bk_word")
            if st.button(tr("♻️ Restore this backup"), **STRETCH):
                if word.strip() == "RESTORE":
                    n = restore_backup(sel)
                    audit("backup_restored", user["username"], sel)
                    st.success(trf("Restored {0} records.", n))
                else:
                    st.error(tr("Type RESTORE (capital letters) to confirm."))


# ======================================================================
# VIEWS/STUDENT — Student side: pick a test -> answer (timed) -> review/edit -> final submit; roster login; My Results.
# ======================================================================
MAX_BYTES = MAX_UPLOAD_MB * 1024 * 1024
SLOTS = {"doc": "w_up_{qid}", "code_file": "w_pyup_{qid}"}
_FLOW_KEYS = ("stu_step", "stu_draft", "stu_primed", "stu_result", "stu_test", "stu_started", "stu_seed")

_TIMER_HTML = """<div id="t" style="font-family:Orbitron,monospace,sans-serif;font-size:26px;color:#fff;text-align:center;
padding:8px;border-radius:14px;background:linear-gradient(120deg,rgba(255,46,151,.35),rgba(123,47,247,.35));
border:1px solid rgba(255,255,255,.3)">⏱️ <span id="s"></span></div>
<script>let r=__SEC__;const s=document.getElementById('s'),t=document.getElementById('t');
function f(){const h=Math.floor(r/3600),m=Math.floor(r%3600/60),x=r%60;
s.textContent=(h?String(h).padStart(2,'0')+':':'')+String(m).padStart(2,'0')+':'+String(x).padStart(2,'0');
if(r<=60)t.style.boxShadow='0 0 25px #ff2e97';if(r<=0){s.textContent='00:00';return}r--;setTimeout(f,1000)}f();</script>"""

if hasattr(st, "fragment"):
    @st.fragment(run_every=10)
    def _expiry_watch(deadline):
        """Every 10 s: when the time is up, rerun the whole app so the answers get auto-submitted."""
        if now() > deadline:
            st.rerun()
else:
    def _expiry_watch(deadline):
        return None


# ------------------------------------------------------------------ state helpers
def _init():
    ss.setdefault("stu_step", "pick")             # pick | answer | review | done
    ss.setdefault("stu_draft", {"name": "", "roll": "", "answers": {}})
    ss.setdefault("stu_primed", False)


def _reset():
    for k in list(ss.keys()):
        if k.startswith("w_") or k in _FLOW_KEYS:
            del ss[k]
    _init()


def _slots_for(q):
    return {"mcq": [], "short": ["doc"], "long": ["doc"], "code": ["code_file", "doc"]}[q["type"]]


def _prime(questions):
    """Copy the saved draft back into widget state when (re)entering the answer step."""
    if ss["stu_primed"]:
        return
    d = ss["stu_draft"]
    for q in questions:
        qid, a = q["id"], d["answers"].get(str(q["id"]), {})
        if q["type"] == "mcq":
            if a.get("choice") in q["options"]:
                ss[f"w_choice_{qid}"] = a["choice"]
            else:
                ss.pop(f"w_choice_{qid}", None)
        elif q["type"] == "code":
            ss[f"w_code_{qid}"] = a.get("code", "")
        else:
            ss[f"w_text_{qid}"] = a.get("text", "")
        for slot in SLOTS:
            ss[f"w_rm_{qid}_{slot}"] = False
    ss["stu_primed"] = True


def _collect(questions):
    """Read every widget into the draft. Returns a list of problems."""
    d, problems = ss["stu_draft"], []
    answers = {}
    for q in questions:
        qid = q["id"]
        prev = d["answers"].get(str(qid), {})
        a = {"choice": None, "text": "", "code": "", "files": {}}
        if q["type"] == "mcq":
            a["choice"] = ss.get(f"w_choice_{qid}")
        elif q["type"] == "code":
            a["code"] = ss.get(f"w_code_{qid}", "")
        else:
            a["text"] = ss.get(f"w_text_{qid}", "")
        for slot in _slots_for(q):
            up = ss.get(SLOTS[slot].format(qid=qid))
            if up is not None:
                if up.size > MAX_BYTES:
                    problems.append(f"Q{q['number']}: '{up.name}' is larger than {MAX_UPLOAD_MB} MB and was ignored.")
                else:
                    a["files"][slot] = {"name": up.name, "bytes": up.getvalue()}
            elif slot in prev.get("files", {}) and not ss.get(f"w_rm_{qid}_{slot}"):
                a["files"][slot] = prev["files"][slot]
        answers[str(qid)] = a
    d["answers"] = answers
    return problems


def _is_answered(q, a):
    if q["type"] == "mcq":
        return bool(a.get("choice"))
    return bool(a.get("text", "").strip() or a.get("code", "").strip() or a.get("files"))


def _identity(store):
    """(name, roll) of whoever is taking the test: the signed-in roster student, or what was typed."""
    s = current_student(store.dept)
    d = ss["stu_draft"]
    return (s["name"], s["roll"]) if s else (d["name"], d["roll"])


# ------------------------------------------------------------------ roster login
def _render_login(store):
    banner(tr("🎓 Student Login"), trf("Department of {0} — sign in with your roll number and PIN", store.dept))
    st.info(tr("Your class teacher gives you a roll number and a 6-digit PIN. Ask them if you have forgotten the PIN."))
    with st.form("student_login"):
        roll = st.text_input(tr("Roll Number"))
        pin = st.text_input(tr("PIN"), type="password", max_chars=6)
        go = st.form_submit_button(tr("🔓 Login"), **STRETCH)
    if go:
        ok, msg = student_login(store.dept, roll, pin)
        if ok:
            st.rerun()
        else:
            st.error(tr(msg))


# ------------------------------------------------------------------ tests available to students
def _available_tests(store, questions):
    tests = sorted([t for t in store.tests() if t.get("published")], key=lambda t: t.get("open_at") or t["created_at"])
    if not tests and questions:    # departments that have not created tests yet: one general test with all questions
        tests = [{"id": "ALL", "title": "General Assessment", "instructions": "", "question_ids": [q["id"] for q in questions],
                  "open_at": "", "close_at": "", "duration_min": 0, "shuffle_questions": False,
                  "shuffle_options": False, "negative": 0.0, "published": True, "created_at": ""}]
    return tests


def _window_text(t):
    o, c = t.get("open_at"), t.get("close_at")
    parts = []
    if o:
        parts.append(trf("Opens: {0}", o[:16]))
    if c:
        parts.append(trf("Closes: {0}", c[:16]))
    return " · ".join(parts)


def _render_pick(store):
    banner(tr("📝 Take Assessment"), trf("Department of {0} — choose a test to begin", store.dept))
    questions = store.questions()
    tests = _available_tests(store, questions)
    if not tests:
        st.warning(tr("No tests have been published for this department yet. Please check back later."))
        return
    student = current_student(store.dept)
    if student:
        name, roll = student["name"], student["roll"]
        st.success(trf("Signed in as **{0}** (Roll {1})", name, roll))
    else:
        c1, c2 = st.columns(2)
        name = c1.text_input(tr("Student Name"), placeholder=tr("e.g. Rahul Sharma"), key="anon_name").strip()
        roll = c2.text_input(tr("Roll Number"), placeholder=tr("e.g. 102"), key="anon_roll").strip()
    submitted = {(s.get("test_id"), norm_roll(s["roll_no"])) for s in store.submissions()}
    at = now()
    by_id = {q["id"]: q for q in questions}
    for t in tests:
        status = test_status(t, at)
        total = sum(by_id[i]["max_marks"] for i in t["question_ids"] if i in by_id)
        icon = {"open": "🟢", "scheduled": "🕒", "closed": "🔒"}[status]
        with st.expander(f"{icon} {tr(t['title'])}", expanded=True):
            if t.get("instructions"):
                st.info(t["instructions"])
            meta = [trf("{0} question(s)", len(t["question_ids"])), trf("Total marks: {0:g}", total)]
            if t.get("duration_min"):
                meta.append(trf("Time limit: {0} min", t["duration_min"]))
            if t.get("negative"):
                meta.append(trf("Negative marking: {0:.0%} of the marks for a wrong MCQ answer", t["negative"]))
            st.caption(" · ".join(meta))
            if _window_text(t):
                st.caption("🗓️ " + _window_text(t))
            already = bool(roll) and (t["id"], norm_roll(roll)) in submitted
            resume = bool(student and store.get_attempt(t["id"], student["roll"]))
            if already:
                st.success(tr("✅ You have already submitted this test."))
            elif status == "scheduled":
                st.info(tr("🕒 This test has not opened yet."))
            elif status == "closed":
                st.warning(tr("🔒 This test is closed."))
            elif st.button(tr("▶️ Resume test") if resume else tr("▶️ Start test"), key=f"start_{t['id']}", type="primary", **STRETCH):
                if not name or not roll:
                    st.error(tr("Please enter both your name and roll number."))
                else:
                    _start(store, t, student, name, roll)


def _start(store, t, student, name, roll):
    if student:
        started = parse_dt(store.start_attempt(t["id"], student["roll"])["started_at"])
        seed = f"{t['id']}-{student['key']}"
    else:
        started = now()
        seed = f"{t['id']}-{secrets.token_hex(4)}"
    deadline = attempt_deadline(t, started)
    if deadline and now() > deadline + timedelta(seconds=LATE_GRACE_SECONDS):
        st.error(tr("⏰ Your time for this test is over."))
        return
    _reset()
    ss.update(stu_test=t["id"], stu_started=started.strftime("%Y-%m-%d %H:%M:%S"), stu_seed=seed, stu_step="answer",
              stu_primed=False, stu_draft={"name": name, "roll": roll, "answers": {}})
    st.rerun()


def _test_context(store):
    """(test, questions in the order this student sees them, deadline) for the running attempt."""
    questions = store.questions()
    t = next((x for x in _available_tests(store, questions) if x["id"] == ss.get("stu_test")), None)
    if t is None:
        _reset()
        st.rerun()
    ids = set(t["question_ids"])
    qs = [dict(q) for q in questions if q["id"] in ids]
    seed = ss["stu_seed"]
    if t.get("shuffle_questions"):
        random.Random(seed).shuffle(qs)
    if t.get("shuffle_options"):
        for q in qs:
            if q["type"] == "mcq":
                opts = list(q["options"])
                random.Random(f"{seed}-{q['id']}").shuffle(opts)
                q["options"] = opts
    deadline = attempt_deadline(t, parse_dt(ss["stu_started"]))
    return t, qs, deadline


def _timer(deadline):
    if not deadline:
        return
    remaining = max(0, int((deadline - now()).total_seconds()))
    render_html(_TIMER_HTML.replace("__SEC__", str(remaining)), height=64)
    _expiry_watch(deadline)


# ------------------------------------------------------------------ step 1: answer
def _question_header(q):
    tag = f" · _{q['identifier']}_" if q.get("identifier") else ""
    st.markdown(trf("#### Q{0}. {1}", q['number'], q['question']))
    st.caption(trf("{0:g} mark(s) · {1}{2}", q['max_marks'], QUESTION_TYPES.get(q['type'], q['type']), tag))


def _file_slot(q, slot, label, types):
    qid = q["id"]
    existing = ss["stu_draft"]["answers"].get(str(qid), {}).get("files", {}).get(slot)
    if existing:
        c1, c2 = st.columns([3, 1])
        c1.caption(trf("📎 Attached: **{0}** ({1:.1f} KB) — upload below to replace", existing['name'], len(existing['bytes']) / 1024))
        c2.checkbox(tr("Remove"), key=f"w_rm_{qid}_{slot}")
    st.file_uploader(tr(label), type=types, key=SLOTS[slot].format(qid=qid))


def _render_answer(store, t, questions, deadline):
    _prime(questions)
    banner(tr(t["title"]), trf("Department of {0} — answer, review, modify, then submit", store.dept))
    _timer(deadline)
    name, roll = _identity(store)
    st.caption(trf("**Name:** {0}  ·  **Roll No.:** {1}", name, roll))
    st.info(tr("💡 Nothing is final yet. After answering you will get a **review screen** where you can still "
            "edit answers and replace uploaded files before the final submission."))
    st.markdown("---")

    for q in questions:
        qid = q["id"]
        _question_header(q)
        if q["type"] == "mcq":
            st.radio(tr("Choose"), q["options"], index=None, key=f"w_choice_{qid}", label_visibility="collapsed")
        elif q["type"] == "short":
            st.text_input(tr("Answer"), placeholder=tr("Type a concise answer…"), key=f"w_text_{qid}", label_visibility="collapsed")
            _file_slot(q, "doc", "📄 Upload handwritten answer (PDF / PNG / JPG) — optional", DOC_EXTS)
        elif q["type"] == "long":
            st.text_area(tr("Answer"), placeholder=tr("Write the detailed answer / derivation…"), height=180,
                         key=f"w_text_{qid}", label_visibility="collapsed")
            _file_slot(q, "doc", "📄 Upload handwritten answer script (PDF / PNG / JPG) — optional", DOC_EXTS)
        else:  # code
            st.text_area(tr("Code"), placeholder=tr("# Paste or type your Python code here (it is stored, never executed)"),
                         height=220, key=f"w_code_{qid}", label_visibility="collapsed")
            _file_slot(q, "code_file", "🐍 Upload code file (.py / .txt editor output)", CODE_EXTS)
            _file_slot(q, "doc", "🖼️ Upload output screenshot / report (PDF / PNG / JPG) — optional", DOC_EXTS)
        st.markdown(tr("<br>"), unsafe_allow_html=True)

    if st.button(tr("👀 Review My Answers →"), type="primary", **STRETCH):
        for p in _collect(questions):
            st.warning(tr(p))
        ss["stu_step"], ss["stu_primed"] = "review", False
        st.rerun()


# ------------------------------------------------------------------ step 2: review
def _preview_files(a):
    for slot, f in a.get("files", {}).items():
        kind = "Code file" if slot == "code_file" else "Document / image"
        st.markdown(trf("📎 **{0}:** `{1}` ({2:.1f} KB)", kind, f['name'], len(f['bytes']) / 1024))
        name = f["name"].lower()
        if name.endswith((".png", ".jpg", ".jpeg")):
            try:
                st.image(f["bytes"], width=380)
            except Exception:  # corrupt / unreadable image
                st.warning(tr("Preview not available for this file (it will still be submitted)."))
        elif name.endswith((".py", ".txt")):
            st.code(f["bytes"].decode("utf-8", errors="replace")[:5000], language="python")


def _render_review(store, t, questions, deadline):
    d = ss["stu_draft"]
    banner(tr("🔍 Review Before Final Submission"), tr("Check everything. You can still go back and change any answer."))
    _timer(deadline)
    name, roll = _identity(store)
    st.markdown(trf("**Name:** {0}  ·  **Roll No.:** {1}  ·  **Department:** {2}", name, roll, store.dept))
    st.markdown("---")
    missing = []
    for q in questions:
        a = d["answers"].get(str(q["id"]), {})
        _question_header(q)
        if not _is_answered(q, a):
            missing.append(q["number"])
            st.error(tr("⚠️ Not answered"))
        elif q["type"] == "mcq":
            st.success(trf("Selected: **{0}**", a['choice']))
        else:
            if a.get("text", "").strip():
                st.info(tr(a["text"]))
            if a.get("code", "").strip():
                st.code(a["code"], language="python")
            _preview_files(a)
        st.markdown(tr("<br>"), unsafe_allow_html=True)

    if missing:
        st.warning(trf("Unanswered question(s): {0}. You may still submit, but unanswered questions get zero.",
                       ", ".join(f"Q{m}" for m in missing)))
    confirm = st.checkbox(tr("✅ I confirm these answers are my own work and I want to submit them."), key="w_confirm")

    c1, c2 = st.columns(2)
    if c1.button(tr("✏️ Edit My Answers"), **STRETCH):
        ss["stu_step"], ss["stu_primed"] = "answer", False
        st.rerun()
    if c2.button(tr("🚀 Final Submit"), type="primary", disabled=not confirm, **STRETCH):
        _final_submit(store, t, questions)


def _final_submit(store, t, questions, auto=False):
    d = ss["stu_draft"]
    student = current_student(store.dept)
    if store.has_roster() and not student:
        st.error(tr("Your login session expired. Please sign in again — your answers are still here."))
        return
    name, roll = _identity(store)
    if store.submission_for(t["id"], roll):
        st.error(tr("A submission already exists for this roll number in this test. Please contact your faculty if this is a mistake."))
        return
    deadline = attempt_deadline(t, parse_dt(ss["stu_started"]))
    late = bool(deadline and now() > deadline + timedelta(seconds=LATE_GRACE_SECONDS))
    pin = None if student else f"{secrets.randbelow(10 ** 6):06d}"
    neg = float(t.get("negative") or 0)
    paper = [{k: q[k] for k in ("id", "number", "identifier", "type", "question", "options", "answer", "max_marks")}
             for q in sorted(questions, key=lambda q: natural_key(q["number"]))]
    marks, answers = {}, {}
    for q in questions:
        a = d["answers"].get(str(q["id"]), {"choice": None, "text": "", "code": "", "files": {}})
        answers[str(q["id"])] = {"choice": a["choice"], "text": a["text"], "code": a["code"], "files": {}}
        if q["type"] == "mcq":
            if not a["choice"]:
                marks[str(q["id"])] = 0.0
            elif a["choice"] == q["answer"]:
                marks[str(q["id"])] = q["max_marks"]
            else:
                marks[str(q["id"])] = -round(q["max_marks"] * neg, 2)
    sid = store.add_submission({
        "department": store.dept, "student_name": name, "roll_no": roll, "timestamp": now_str(),
        "test_id": t["id"], "test_title": t["title"], "started_at": ss["stu_started"], "late": late, "auto_submitted": auto,
        "pin": hash_secret(pin, iterations=200_000) if pin else None, "paper": paper, "answers": answers,
        "marks": marks, "remarks": {}, "overall_feedback": "", "status": "submitted",
    })
    for q in questions:  # persist uploads only now, under sanitised unique names
        for slot, f in d["answers"].get(str(q["id"]), {}).get("files", {}).items():
            rel = store.save_upload(sid, q["id"], slot, f["name"], f["bytes"])
            answers[str(q["id"])]["files"][slot] = {"name": f["name"], "path": rel}
    store.update_submission(sid, {"answers": answers})
    mcq_total = sum(q["max_marks"] for q in questions if q["type"] == "mcq")
    ss["stu_result"] = {"id": sid, "pin": pin, "name": name, "mcq_got": max(0.0, sum(marks.values())),
                        "mcq_total": mcq_total, "celebrated": False, "late": late, "auto": auto, "test": t["title"]}
    ss["stu_step"] = "done"
    ss["stu_primed"] = False
    st.rerun()


# ------------------------------------------------------------------ step 3: done
def _render_done():
    r = ss["stu_result"]
    st.success(trf("🎉 Assessment submitted successfully, {0}!", r['name']))
    if r.get("auto"):
        st.warning(tr("⏰ Time was up, so your answers were submitted automatically."))
    if r.get("late"):
        st.warning(tr("⚠️ This submission arrived after the deadline and has been marked as late."))
    if not r["celebrated"]:
        st.balloons()
        r["celebrated"] = True
    st.markdown(trf("### Submission ID: `{0}`", r['id']))
    if r["pin"]:
        st.markdown(trf("<div class='pin-card'>YOUR PRIVATE ACCESS PIN<div class='pin'>{0}</div><div>Shown only once — you need <b>Submission ID + PIN</b> to download your report card.</div></div>", r['pin']),
                    unsafe_allow_html=True)
    else:
        st.info(tr("Your result will appear under **My Report Card** after your teacher finishes the evaluation."))
    if r["mcq_total"]:
        c1, c2 = st.columns(2)
        c1.metric(tr("MCQ marks (auto-graded)"), f"{r['mcq_got']:g} / {r['mcq_total']:g}")
        c2.metric(tr("Other answers"), tr("Awaiting faculty evaluation ⏳"))
    if r["pin"]:
        st.download_button(tr("📥 Download Submission Receipt"),
                           f"Submission ID: {r['id']}\nAccess PIN: {r['pin']}\nStudent: {r['name']}\n"
                           f"Keep this safe. Use both on the 'My Report Card' page once evaluation is finished.\n",
                           file_name=f"receipt_{r['id']}.txt", **STRETCH)
    if st.button(tr("🔄 Back to the test list"), **STRETCH):
        _reset()
        st.rerun()


# ------------------------------------------------------------------ entry points
def render_assessment(store):
    _init()
    if store.has_roster() and not current_student(store.dept):
        _render_login(store)
        return
    step = ss["stu_step"]
    if step == "done":
        _render_done()
    elif step in ("answer", "review"):
        t, questions, deadline = _test_context(store)
        if deadline and now() > deadline:              # time is up -> submit whatever the student has typed
            if step == "answer":
                _collect(questions)
            _final_submit(store, t, questions, auto=True)
            return
        if step == "review":
            _render_review(store, t, questions, deadline)
        else:
            _render_answer(store, t, questions, deadline)
    else:
        _render_pick(store)


def _show_report(store, sub):
    sid = sub["submission_id"]
    t = totals(sub)
    st.success(trf("Report card ready for **{0}** (Roll {1})", sub['student_name'], sub['roll_no']))
    if sub.get("test_title"):
        st.caption(trf("Assessment: {0}", sub["test_title"]))
    c1, c2, c3, c4 = st.columns(4)
    c1.metric(tr("Marks"), f"{t['obtained']:g} / {t['max']:g}")
    c2.metric(tr("Percentage"), f"{t['percent']:.1f}%")
    c3.metric(tr("Grade"), t["grade"])
    c4.metric(tr("Result"), tr("PASS ✅") if t["passed"] else tr("FAIL ❌"))
    try:
        data = store.load_report(sid) or build_report_pdf(sub, store.dept)
        st.download_button(tr("📄 Download Official Report Card (PDF)"), data,
                           file_name=f"ReportCard_{sid}.pdf", mime="application/pdf", key=f"pdf_{sid}", **STRETCH)
        st.download_button(tr("🖨️ Printable report card — English + বাংলা (HTML)"),
                           build_report_html(sub, store.dept).encode("utf-8"),
                           file_name=f"ReportCard_{sid}.html", mime="text/html", key=f"html_{sid}", **STRETCH)
        st.caption(tr("Use the HTML version if the name or remarks are in Bengali: open it, then Print → Save as PDF."))
    except ImportError:
        st.error(tr("PDF support (reportlab) is not installed on the server."))


def _render_my_results(store, student):
    banner(tr("🎓 My Report Card"), trf("{0} · Roll {1}", student["name"], student["roll"]))
    mine = [s for s in store.submissions() if norm_roll(s["roll_no"]) == student["key"]]
    if not mine:
        st.info(tr("You have not submitted any test yet."))
        return
    rows, done = [], []
    for s in sorted(mine, key=lambda s: s["timestamp"]):
        t = totals(s)
        fin = s["status"] == "finalized"
        rows.append({"Test": s.get("test_title") or "—", "Submitted": s["timestamp"][:16],
                     "Status": tr("Finalised") if fin else tr("Pending"),
                     "Marks": f"{t['obtained']:g} / {t['max']:g}" if fin else "—",
                     "Percent": round(t["percent"], 1) if fin else None, "Grade": t["grade"] if fin else "—"})
        if fin:
            done.append((s, t))
    show_df(pd.DataFrame(rows))
    if done:
        c1, c2, c3 = st.columns(3)
        c1.metric(tr("Tests evaluated"), len(done))
        c2.metric(tr("Average"), f"{sum(t['percent'] for _, t in done) / len(done):.1f}%")
        c3.metric(tr("Best score"), f"{max(t['percent'] for _, t in done):.1f}%")
        if len(done) >= 2:
            st.markdown(tr("**Your progress across tests (%)**"))
            st.line_chart(pd.DataFrame({"%": [t["percent"] for _, t in done]},
                                       index=[f"{i + 1}. {s.get('test_title') or '—'}" for i, (s, _) in enumerate(done)]),
                          color="#00e5ff")
        by_id = {s["submission_id"]: s for s, _ in done}
        pick = st.selectbox(tr("Choose a report card"), list(by_id), key=f"res_pick_{ss.get('lang', 'en')}",
                            format_func=lambda i: f"{by_id[i].get('test_title') or '—'} · {by_id[i]['timestamp'][:10]}")
        _show_report(store, by_id[pick])
    else:
        st.info(tr("⏳ Your answers are received, but the faculty has not finalised the evaluation yet."))


def render_report_card(store):
    student = current_student(store.dept)
    if store.has_roster():
        if not student:
            _render_login(store)
        else:
            _render_my_results(store, student)
        return
    banner(tr("🎓 My Report Card"), tr("Enter the Submission ID and PIN you received after submitting"))
    with st.form("card_lookup"):
        sid = st.text_input(tr("Submission ID"), placeholder=trf("e.g. {0}-0001", store.slug[:3].upper())).strip().upper()
        pin = st.text_input(tr("Access PIN"), type="password", max_chars=6)
        go = st.form_submit_button(tr("🔎 Find My Report Card"), **STRETCH)
    if go:
        key = f"pin:{store.slug}:{sid}"
        wait = lock_remaining(key)
        sub = store.get_submission(sid) if sid else None
        if wait:
            st.error(trf("Too many wrong PINs. Try again in {0} minute(s).", wait // 60 + 1))
        elif not sub or not sub.get("pin") or not verify_secret(pin, sub["pin"]):
            register_failure(key if sub else f"pin:{store.slug}:unknown")
            st.error(tr("Submission ID or PIN is incorrect."))
        else:
            clear_failures(key)
            ss["card_sid"] = sid
    sid = ss.get("card_sid")
    sub = store.get_submission(sid) if sid else None
    if sub:
        if sub["status"] != "finalized":
            st.info(tr("⏳ Your answers are received, but the faculty has not finalised the evaluation yet."))
        else:
            _show_report(store, sub)


# ======================================================================
# VIEWS/MATERIALS — Syllabus & study materials: students browse/download, teachers upload/manage (per-department folders).
# ======================================================================
def _fmt_size(n):
    return f"{n / 1024:.0f} KB" if n < 1024 * 1024 else f"{n / 1024 / 1024:.1f} MB"


def _sem_label(code):
    return tr("General") if code == "General" else trf("Semester {0}", code)


def _cat_label(code):
    return tr(MATERIAL_CATEGORIES.get(code, code))


@st.cache_data(max_entries=6, ttl=900, show_spinner=False)
def _material_bytes(dept, mid, stamp):
    return DeptStore(dept).read_material(mid)


# ------------------------------------------------------------------ students (and everyone): browse + download
def render_study_materials(store):
    banner(tr("📚 Study Materials & Syllabus"),
           trf("Department of {0} — pick a folder, choose a material and download", store.dept))
    mats = store.materials()
    if not mats:
        st.info(tr("No study materials have been uploaded for this department yet. Please check back later."))
        return

    c1, c2, c3 = st.columns([2, 1.4, 2])
    cat = c1.selectbox(tr("Folder"), ["all"] + list(MATERIAL_CATEGORIES), key=f"mat_cat_{lang()}",
                       format_func=lambda c: tr("All folders") if c == "all" else "📁 " + _cat_label(c))
    sem = c2.selectbox(tr("Semester"), ["all"] + SEMESTERS, key=f"mat_sem_{lang()}",
                       format_func=lambda c: tr("All semesters") if c == "all" else _sem_label(c))
    q = c3.text_input(tr("Search title or subject"), key="mat_q").strip().lower()

    shown = [m for m in mats
             if (cat == "all" or m["category"] == cat) and (sem == "all" or m["semester"] == sem)
             and (not q or q in m["title"].lower() or q in m.get("subject", "").lower())]
    st.caption(trf("{0} material(s) found", len(shown)))
    if not shown:
        st.warning(tr("Nothing matches your filters."))
        return

    show_df(pd.DataFrame([{
        "Title": m["title"], "Folder": _cat_label(m["category"]), "Subject / Paper": m.get("subject", ""),
        "Semester": _sem_label(m["semester"]), "Size": _fmt_size(m["size"]), "Uploaded": m["uploaded_at"][:10],
    } for m in shown]))

    by_id = {m["id"]: m for m in shown}
    mid = st.selectbox(tr("Choose a material to download"), list(by_id), key=f"mat_choice_{lang()}",
                       format_func=lambda i: f"{by_id[i]['title']}  ·  {_cat_label(by_id[i]['category'])}")
    m = by_id[mid]
    st.markdown("### " + m["title"])
    st.caption(trf("📁 {0} › {1}", store.dept, _cat_label(m["category"])))
    if m.get("subject"):
        st.markdown(trf("**Subject / Paper:** {0}", m["subject"]))
    if m.get("description"):
        st.info(m["description"])
    st.caption(trf("Uploaded by {0} on {1} · {2}", m.get("uploaded_by", "-"), m["uploaded_at"], _fmt_size(m["size"])))
    data = _material_bytes(store.dept, mid, m["uploaded_at"])
    if data is None:
        st.warning(tr("File is missing in storage."))
    else:
        st.download_button(trf("⬇️ Download {0}", m["filename"]), data, file_name=m["filename"],
                           key=f"dlm_{mid}", **STRETCH)


# ------------------------------------------------------------------ teachers / admin: upload + manage
def render_materials_manager(store, user):
    banner(tr("📤 Upload Study Materials"),
           trf("Department of {0} — add syllabus, notes and other materials to this department's folders", store.dept))
    if "mat_ok" in ss:
        n, cat = ss.pop("mat_ok")
        st.success(trf("Uploaded {0} file(s) to the “{1}” folder.", n, _cat_label(cat)))
    if "mat_msg" in ss:
        st.success(tr(ss.pop("mat_msg")))
    t_up, t_manage = st.tabs([tr("📤 Upload"), tr("🗂️ Manage uploaded files")])

    with t_up:
        st.caption(trf("Files are saved only in the {0} department's own folders — other departments never see them.", store.dept))
        ver = ss.setdefault("mat_ver", 0)
        with st.form(f"mat_upload_{ver}"):
            cat = st.selectbox(tr("Folder (category)"), list(MATERIAL_CATEGORIES),
                               format_func=lambda c: "📁 " + _cat_label(c))
            title = st.text_input(tr("Title (optional if you upload several files)"))
            c1, c2 = st.columns(2)
            subject = c1.text_input(tr("Subject / Paper (optional)"), placeholder=tr("e.g. Mechanics · PHYS-101"))
            sem = c2.selectbox(tr("Semester"), SEMESTERS, format_func=_sem_label)
            desc = st.text_area(tr("Description (optional)"))
            files = st.file_uploader(tr("Choose file(s) to upload"), type=MATERIAL_EXTS, accept_multiple_files=True)
            go = st.form_submit_button(tr("⬆️ Upload"), **STRETCH)
        st.caption(trf("Allowed: PDF, Word, PowerPoint, Excel, text, images, ZIP · max {0} MB per file", MAX_MATERIAL_MB))
        if go:
            if not files:
                st.error(tr("Please choose at least one file."))
            else:
                done = 0
                for f in files:
                    ext = Path(f.name).suffix.lower().lstrip(".")
                    if ext not in MATERIAL_EXTS:
                        st.error(trf("'{0}': file type not allowed.", f.name))
                    elif f.size > MAX_MATERIAL_MB * 1024 * 1024:
                        st.error(trf("'{0}' is larger than {1} MB and was skipped.", f.name, MAX_MATERIAL_MB))
                    else:
                        stem = Path(f.name).stem
                        name = (title.strip() if title.strip() and len(files) == 1
                                else f"{title.strip()} – {stem}" if title.strip() else stem)
                        store.add_material({"title": name, "category": cat, "subject": subject.strip(),
                                            "semester": sem, "description": desc.strip(),
                                            "uploaded_by": user["username"]}, f.name, f.getvalue())
                        done += 1
                if done:
                    ss["mat_ok"] = (done, cat)
                    ss["mat_ver"] = ver + 1
                    st.rerun()

    with t_manage:
        mats = store.materials()
        if not mats:
            st.info(tr("No materials uploaded yet."))
            return
        st.metric(tr("Files in this department"), len(mats))
        show_df(pd.DataFrame([{
            "ID": m["id"], "Title": m["title"], "Folder": _cat_label(m["category"]),
            "Semester": _sem_label(m["semester"]), "Size": _fmt_size(m["size"]), "Uploaded": m["uploaded_at"][:10],
        } for m in mats]))
        by_id = {m["id"]: m for m in mats}
        mid = st.selectbox(tr("Select material"), list(by_id), key="mat_edit_sel",
                           format_func=lambda i: f"{i} · {by_id[i]['title']}")
        m = by_id[mid]
        st.caption(tr("To move a file to another folder, delete it and upload it again."))
        with st.form(f"mat_edit_{mid}"):
            e_title = st.text_input(tr("Title"), value=m["title"])
            e_subject = st.text_input(tr("Subject / Paper (optional)"), value=m.get("subject", ""))
            e_sem = st.selectbox(tr("Semester"), SEMESTERS, index=SEMESTERS.index(m["semester"]),
                                 format_func=_sem_label)
            e_desc = st.text_area(tr("Description (optional)"), value=m.get("description", ""))
            a, b = st.columns(2)
            save = a.form_submit_button(tr("💾 Save changes"), **STRETCH)
            confirm = b.checkbox(tr("Confirm deletion"))
            delete = b.form_submit_button(tr("🗑️ Delete"), **STRETCH)
        if save:
            if not e_title.strip():
                st.error(tr("Title cannot be empty."))
            else:
                store.update_material(mid, {"title": e_title.strip(), "subject": e_subject.strip(),
                                            "semester": e_sem, "description": e_desc.strip()})
                ss["mat_msg"] = "Updated."
                st.rerun()
        if delete:
            if confirm:
                store.delete_material(mid)
                ss["mat_msg"] = "Deleted."
                st.rerun()
            else:
                st.warning(tr("Tick **Confirm deletion** first."))


# ======================================================================
# VIEWS/TESTS — Teacher: create and manage tests - question selection, opening/closing time, time limit, shuffling, negative marking.
# ======================================================================
NEG_LABELS = {0.0: "No negative marking", 0.25: "¼ of the question's marks", 1 / 3: "⅓ of the question's marks",
              0.5: "½ of the question's marks"}
STATUS_LABELS = {"draft": "Draft", "scheduled": "Scheduled", "open": "Open", "closed": "Closed"}


def _neg_label(v):
    return tr(NEG_LABELS.get(v, f"{v:.0%}"))


def _status(t):
    return "draft" if not t.get("published") else test_status(t, now())


def _editor(store, prefix, test=None):
    """Draws the test form. Returns the data dict when the teacher presses Save, else None."""
    qs = store.questions()
    if not qs:
        st.warning(tr("Add questions in the Question Creator first — a test is made from the question bank."))
        return None
    by_id = {q["id"]: q for q in qs}
    t = test or {}
    k = lambda n: f"{prefix}_{n}"
    st.caption(trf("All dates and times are in {0}.", TIMEZONE))
    title = st.text_input(tr("Test title"), value=t.get("title", ""), placeholder=tr("e.g. Internal Assessment 1"), key=k("title"))
    instr = st.text_area(tr("Instructions for students (optional)"), value=t.get("instructions", ""), key=k("instr"))
    default = [i for i in t.get("question_ids", list(by_id)) if i in by_id]
    chosen = st.multiselect(tr("Questions in this test"), list(by_id), default=default, key=k("qs"),
                            format_func=lambda i: f"Q{by_id[i]['number']} · {by_id[i]['question'][:60]} ({by_id[i]['max_marks']:g})")
    st.caption(trf("Total marks: {0:g}", sum(by_id[i]["max_marks"] for i in chosen)))

    o, c = parse_dt(t.get("open_at")), parse_dt(t.get("close_at"))
    c1, c2 = st.columns(2)
    use_open = c1.checkbox(tr("Set an opening time"), value=bool(o), key=k("use_open"))
    open_at = ""
    if use_open:
        base = o or now().replace(second=0, microsecond=0)
        od = c1.date_input(tr("Opens on"), value=base.date(), key=k("od"))
        ot = c1.time_input(tr("Opening time"), value=base.time(), key=k("ot"))
        open_at = f"{od} {ot.strftime('%H:%M')}:00"
    use_close = c2.checkbox(tr("Set a closing time"), value=bool(c), key=k("use_close"))
    close_at = ""
    if use_close:
        base = c or (now() + timedelta(days=1)).replace(second=0, microsecond=0)
        cd = c2.date_input(tr("Closes on"), value=base.date(), key=k("cd"))
        ct = c2.time_input(tr("Closing time"), value=base.time(), key=k("ct"))
        close_at = f"{cd} {ct.strftime('%H:%M')}:00"

    dur = st.number_input(tr("Time limit in minutes (0 = no time limit)"), min_value=0, max_value=600, step=5,
                          value=int(t.get("duration_min") or 0), key=k("dur"))
    s1, s2 = st.columns(2)
    shuf_q = s1.checkbox(tr("Shuffle the order of questions"), value=bool(t.get("shuffle_questions")), key=k("sq"))
    shuf_o = s2.checkbox(tr("Shuffle the options of MCQs"), value=bool(t.get("shuffle_options")), key=k("so"))
    choices = NEGATIVE_MARKING_CHOICES
    cur = float(t.get("negative") or 0)
    idx = min(range(len(choices)), key=lambda i: abs(choices[i] - cur))
    neg = st.selectbox(tr("Negative marking for wrong MCQ answers"), choices, index=idx,
                       format_func=_neg_label, key=k(f"neg_{lang()}"))
    published = st.checkbox(tr("Publish (visible to students)"), value=t.get("published", True), key=k("pub"))
    if dur and not store.has_roster():
        st.warning(tr("There is no student roster yet, so a student could restart the timer by refreshing the page. "
                      "Import a class list (👥 Students) to enforce the time limit."))
    if st.button(tr("💾 Save test"), type="primary", key=k("save"), **STRETCH):
        if not title.strip():
            st.error(tr("Please give the test a title."))
        elif not chosen:
            st.error(tr("Select at least one question."))
        elif open_at and close_at and parse_dt(close_at) <= parse_dt(open_at):
            st.error(tr("The closing time must be after the opening time."))
        else:
            return {"title": title.strip(), "instructions": instr.strip(),
                    "question_ids": sorted(chosen, key=lambda i: natural_key(by_id[i]["number"])),
                    "open_at": open_at, "close_at": close_at, "duration_min": int(dur),
                    "shuffle_questions": shuf_q, "shuffle_options": shuf_o, "negative": float(neg), "published": published}
    return None


def render_tests_manager(store, user):
    banner(tr("🧪 Tests"), trf("Department of {0} — schedule tests, set time limits and choose their questions", store.dept))
    if "test_msg" in ss:
        st.success(tr(ss.pop("test_msg")))
    t_new, t_manage = st.tabs([tr("➕ Create test"), tr("📋 Manage tests")])

    with t_new:
        ver = ss.setdefault("test_ver", 0)
        data = _editor(store, f"newt{ver}")
        if data:
            store.add_test({**data, "created_by": user["username"]})
            ss["test_msg"] = "Test saved."
            ss["test_ver"] = ver + 1
            st.rerun()

    with t_manage:
        tests = store.tests()
        if not tests:
            st.info(tr("No tests yet. Create one in the first tab — until then students see one general test with all questions."))
            return
        counts = {}
        for s in store.submissions():
            counts[s.get("test_id")] = counts.get(s.get("test_id"), 0) + 1
        by_q = {q["id"]: q for q in store.questions()}
        show_df(pd.DataFrame([{
            "ID": t["id"], "Title": t["title"], "Status": tr(STATUS_LABELS[_status(t)]),
            "Opens": (t.get("open_at") or "—")[:16], "Closes": (t.get("close_at") or "—")[:16],
            "Minutes": str(t.get("duration_min") or "—"), "Questions": len(t["question_ids"]),
            "Marks": sum(by_q[i]["max_marks"] for i in t["question_ids"] if i in by_q),
            "Submissions": counts.get(t["id"], 0),
        } for t in tests]))
        by_id = {t["id"]: t for t in tests}
        tid = st.selectbox(tr("Select test"), list(by_id), key="test_sel", format_func=lambda i: f"{i} · {by_id[i]['title']}")
        t = by_id[tid]
        data = _editor(store, f"edit_{tid}", t)
        if data:
            store.update_test(tid, data)
            ss["test_msg"] = "Test updated."
            st.rerun()
        st.markdown("---")
        ok = st.checkbox(tr("Confirm deletion"), key=f"deltest_ok_{tid}")
        if st.button(tr("🗑️ Delete test"), key=f"deltest_{tid}", **STRETCH):
            if ok:
                store.delete_test(tid)
                ss["test_msg"] = "Test deleted."
                st.rerun()
            else:
                st.warning(tr("Tick **Confirm deletion** first."))
        st.caption(tr("Deleting a test does not delete the answers students already submitted."))


# ======================================================================
# VIEWS/ROSTER — Teacher: class roster. Importing it switches the department to roll-number + PIN student login.
# ======================================================================
_TEMPLATE = "roll,name,semester\n101,Rahul Sharma,1\n102,Ananya Das,1\n"
_ROLL = ("roll", "roll no", "roll no.", "roll number", "rollno", "id", "student id", "reg no", "registration no")
_NAME = ("name", "student name", "student", "full name")
_SEM = ("semester", "sem", "section", "class")


def _parse(text):
    """CSV / tab / semicolon text -> [{roll, name, semester}]. Header row optional."""
    text = text.lstrip("\ufeff").strip()
    if not text:
        return []
    first = text.splitlines()[0]
    delim = max(",\t;", key=first.count) if any(d in first for d in ",\t;") else ","
    rows = [[c.strip() for c in r] for r in csv.reader(io.StringIO(text), delimiter=delim) if any(c.strip() for c in r)]
    ri, ni, si, start = 0, 1, 2, 0
    head = [c.lower() for c in rows[0]]
    if any(h in _ROLL for h in head) and any(h in _NAME for h in head):
        ri = next(i for i, h in enumerate(head) if h in _ROLL)
        ni = next(i for i, h in enumerate(head) if h in _NAME)
        si = next((i for i, h in enumerate(head) if h in _SEM), None)
        start = 1
    out = []
    for r in rows[start:]:
        if len(r) > max(ri, ni):
            out.append({"roll": r[ri], "name": r[ni], "semester": r[si] if si is not None and len(r) > si else ""})
    return out


def _show_credentials():
    creds = ss.get("roster_creds")
    if not creds:
        return
    st.warning(tr("🔑 Write down or download these PINs NOW. They are stored only in scrambled form and cannot be shown again "
                  "(you can always generate a new PIN for a student)."))
    df = pd.DataFrame(creds).rename(columns={"roll": "Roll", "name": "Name", "pin": "PIN"})
    show_df(df)
    st.download_button(tr("📥 Download PIN sheet (CSV)"), df.to_csv(index=False).encode("utf-8-sig"),
                       file_name="student_pins.csv", mime="text/csv", **STRETCH)
    if st.button(tr("✅ I have saved the PINs — clear them from the screen"), **STRETCH):
        ss.pop("roster_creds", None)
        st.rerun()


def render_roster_manager(store, user):
    banner(tr("👥 Student Roster & Logins"), trf("Department of {0} — class list with roll numbers and private PINs", store.dept))
    roster = store.roster()
    if roster:
        st.success(trf("Student login is ON: {0} student(s) on the roster. Only they can take tests here.", len(roster)))
    else:
        st.info(tr("No roster yet — students type their own name and roll number. Import a class list to switch on "
                   "roll-number + PIN login (this also enforces one attempt per student and test time limits)."))
    _show_credentials()
    t_import, t_list = st.tabs([tr("📥 Import class list"), tr("👥 Students")])

    with t_import:
        st.caption(tr("Columns: roll, name, and optionally semester. A header row is recommended."))
        st.download_button(tr("📄 Download CSV template"), _TEMPLATE.encode("utf-8"), file_name="roster_template.csv",
                           mime="text/csv", **STRETCH)
        up = st.file_uploader(tr("Upload class list (CSV)"), type=["csv", "txt"], key="roster_file")
        pasted = st.text_area(tr("…or paste it here (one student per line: roll, name, semester)"), key="roster_paste", height=120)
        reset = st.checkbox(tr("Also generate new PINs for students who are already on the roster"), key="roster_reset")
        if st.button(tr("📥 Import students"), type="primary", **STRETCH):
            text = up.getvalue().decode("utf-8-sig", errors="replace") if up is not None else pasted
            rows = _parse(text)
            if not rows:
                st.error(tr("No students found. Check the columns and try again."))
            else:
                with st.spinner(tr("Creating logins…")):
                    creds, updated = store.import_students(rows, reset_existing=reset)
                ss["roster_creds"] = creds
                st.success(trf("Imported: {0} new, {1} updated.", len(creds), updated))
                st.rerun()

    with t_list:
        roster = store.roster()
        if not roster:
            st.info(tr("The roster is empty."))
        else:
            q = st.text_input(tr("Search roll or name"), key="roster_q").strip().lower()
            items = [(k, v) for k, v in sorted(roster.items()) if not q or q in k.lower() or q in v["name"].lower()]
            show_df(pd.DataFrame([{"Roll": v["roll"], "Name": v["name"], "Semester": v.get("semester", ""),
                                   "Added": v.get("created", "")[:10]} for _, v in items]))
            if items:
                by_key = dict(items)
                key = st.selectbox(tr("Select student"), list(by_key), key="roster_sel",
                                   format_func=lambda k: f"{by_key[k]['roll']} · {by_key[k]['name']}")
                c1, c2 = st.columns(2)
                if c1.button(tr("🔑 Generate new PIN"), **STRETCH):
                    pin = store.reset_student_pin(key)
                    ss["roster_creds"] = [{"roll": by_key[key]["roll"], "name": by_key[key]["name"], "pin": pin}]
                    st.rerun()
                ok = c2.checkbox(tr("Confirm deletion"), key=f"roster_del_ok_{key}")
                if c2.button(tr("🗑️ Remove student"), **STRETCH):
                    if ok:
                        store.delete_student(key)
                        st.rerun()
                    else:
                        st.warning(tr("Tick **Confirm deletion** first."))
        st.markdown("---")
        with st.form("roster_add_one", clear_on_submit=True):
            st.markdown(tr("#### ➕ Add one student"))
            a, b, c = st.columns([1, 2, 1])
            roll = a.text_input(tr("Roll Number"))
            name = b.text_input(tr("Student Name"))
            sem = c.selectbox(tr("Semester"), SEMESTERS, format_func=lambda s: tr("General") if s == "General" else trf("Semester {0}", s))
            add = st.form_submit_button(tr("Add student"), **STRETCH)
        if add:
            creds, _ = store.import_students([{"roll": roll, "name": name, "semester": "" if sem == "General" else sem}])
            if creds:
                ss["roster_creds"] = creds
                st.rerun()
            else:
                st.error(tr("Enter a roll number and a name (a student with this roll may already exist)."))
        if roster:
            st.markdown("---")
            st.caption(tr("Removing the whole roster switches this department back to anonymous mode (students type their own name and roll)."))
            ok = st.checkbox(tr("Confirm deletion"), key="roster_clear_ok")
            if st.button(tr("🗑️ Remove the whole roster"), **STRETCH):
                if ok:
                    store.clear_roster()
                    st.rerun()
                else:
                    st.warning(tr("Tick **Confirm deletion** first."))


# ======================================================================
# VIEWS/CREATOR — Teacher question creator: numbering, identifiers, weightage, manager and OCR importer.
# ======================================================================
def _flash():
    if "form_success" in ss:
        st.success(tr(ss.pop("form_success")))


def _add_section(store):
    st.markdown(tr("#### ➕ Add New Question"))
    ver = ss.setdefault("new_q_ver", 0)
    k = lambda name: f"{name}_{ver}"

    qtype = st.selectbox(tr("Question Type"), list(QUESTION_TYPES), key=k("ntype") + "_" + lang(),
                         format_func=lambda c: tr(QUESTION_TYPES[c]))

    c1, c2, c3 = st.columns([1, 2, 1])
    number = c1.text_input(tr("Question No."), value=store.free_number(), key=k("nnum"),
                           help=tr("Printed on the paper and report card, e.g. 1, 2a, Q3"))
    identifier = c2.text_input(tr("Identifier / Topic tag (optional)"), placeholder=tr("e.g. Unit 2 – Kinematics · CO3"), key=k("nid"))
    marks = c3.number_input(tr("Max Marks"), min_value=0.5, max_value=100.0, step=0.5,
                            value=DEFAULT_MARKS[qtype], key=k(f"nmarks_{qtype}"))

    prompt = st.text_area(tr("Question Prompt"), placeholder=tr("Enter question text…"), key=k("nprompt"))
    options, answer = [], ""
    if qtype == "mcq":
        a, b = st.columns(2)
        raw = [a.text_input(tr("Option A"), key=k("oa")), b.text_input(tr("Option B"), key=k("ob")),
               a.text_input(tr("Option C"), key=k("oc")), b.text_input(tr("Option D"), key=k("od"))]
        options = [o.strip() for o in raw if o.strip()]
        if options:
            answer = st.selectbox(tr("Correct Option"), options, key=k("ocorrect"))
        else:
            st.info(tr("💡 Type at least 2 options above to activate the correct-option selector."))
    elif qtype == "code":
        answer = st.text_area(tr("Reference solution / marking rubric"), key=k("nans"),
                              placeholder=tr("Expected logic, test cases, rubric…"))
    else:
        answer = st.text_area(tr("Model answer / evaluation guidelines"), key=k("nans"))

    if st.button(tr("💾 Save Question to Bank"), type="primary", **STRETCH):
        if not prompt.strip():
            st.error(tr("Question prompt cannot be empty."))
        elif not number.strip():
            st.error(tr("Please give the question a number / identifier."))
        elif store.number_exists(number):
            st.error(trf("Question number **{0}** is already used in this department.", number.strip()))
        elif qtype == "mcq" and len(options) < 2:
            st.error(tr("MCQs require at least 2 options."))
        else:
            store.add_question({
                "number": number.strip(), "identifier": identifier.strip(), "type": qtype,
                "question": prompt.strip(), "options": options if qtype == "mcq" else [],
                "answer": answer.strip(), "max_marks": float(marks),
            })
            ss["form_success"] = f"Saved Question {number.strip()} ({marks:g} marks)."
            ss["new_q_ver"] = ver + 1
            st.rerun()


def _bank_overview(store):
    qs = store.questions()
    st.markdown(tr("#### 📚 Question Bank"))
    if not qs:
        st.info(tr("No questions yet — add the first one above."))
        return qs
    c1, c2, c3 = st.columns(3)
    c1.metric(tr("Questions"), len(qs))
    c2.metric(tr("Total Marks"), f"{sum(q['max_marks'] for q in qs):g}")
    c3.metric(tr("MCQs"), sum(q["type"] == "mcq" for q in qs))
    df = pd.DataFrame([{
        "No.": q["number"], "Identifier": q["identifier"], "Type": q["type"].upper(),
        "Marks": q["max_marks"], "Question": q["question"][:90] + ("…" if len(q["question"]) > 90 else ""),
    } for q in qs])
    show_df(df)
    return qs


def _edit_section(store, qs):
    if not qs:
        return
    st.markdown(tr("#### ✏️ Modify or Remove a Question"))
    st.caption(tr("Edits never change submissions already made — each submission keeps its own copy of the paper."))
    labels = {f"Q{q['number']} · {q['question'][:50]}…": q["id"] for q in qs}
    sel = st.selectbox(tr("Select question"), list(labels), key="edit_sel")
    q = next(x for x in qs if x["id"] == labels[sel])
    with st.form(f"edit_form_{q['id']}"):
        c1, c2, c3 = st.columns([1, 2, 1])
        number = c1.text_input(tr("Question No."), value=q["number"])
        identifier = c2.text_input(tr("Identifier / Topic"), value=q["identifier"])
        marks = c3.number_input(tr("Max Marks"), min_value=0.5, max_value=100.0, step=0.5, value=float(q["max_marks"]))
        prompt = st.text_area(tr("Prompt"), value=q["question"])
        opts_text = None
        if q["type"] == "mcq":
            opts_text = st.text_area(tr("Options (one per line)"), value="\n".join(q["options"]))
        answer = st.text_area(tr("Correct option / model answer / rubric"), value=q["answer"])
        col_a, col_b = st.columns(2)
        upd = col_a.form_submit_button(tr("🔄 Update"), **STRETCH)
        confirm_del = col_b.checkbox(tr("Confirm deletion"))
        dele = col_b.form_submit_button(tr("🗑️ Delete"), **STRETCH)

    if upd:
        options = [o.strip() for o in opts_text.splitlines() if o.strip()] if opts_text is not None else q["options"]
        if not prompt.strip() or not number.strip():
            st.error(tr("Number and prompt are required."))
        elif store.number_exists(number, exclude_id=q["id"]):
            st.error(tr("That question number is already used."))
        elif q["type"] == "mcq" and (len(options) < 2 or answer.strip() not in options):
            st.error(tr("MCQ needs ≥2 options and the answer must exactly match one of them."))
        else:
            data = [dict(x) for x in store.raw_questions()]
            for x in data:
                if x["id"] == q["id"]:
                    x.update(number=number.strip(), identifier=identifier.strip(), max_marks=float(marks),
                             question=prompt.strip(), answer=answer.strip(), options=options)
            store.save_questions(data)
            ss["form_success"] = f"Updated Question {number.strip()}."
            st.rerun()
    if dele:
        if confirm_del:
            store.save_questions([x for x in store.raw_questions() if x["id"] != q["id"]])
            ss["form_success"] = f"Deleted Question {q['number']}."
            st.rerun()
        else:
            st.warning(tr("Tick **Confirm deletion** first."))


def _import_section(store):
    st.markdown(tr("#### 📄 Smart PDF / Scanned Image Importer"))
    up = st.file_uploader(tr("Upload Question Paper"), type=DOC_EXTS, key="import_file")
    c1, c2 = st.columns(2)
    default_marks = c1.number_input(tr("Marks per imported question"), 0.5, 100.0, 5.0, 0.5)
    itype = c2.selectbox(tr("Import as type"), ["long", "short", "code"], format_func=lambda c: tr(QUESTION_TYPES[c]))
    if up is None or not st.button(tr("🚀 Process & Import Questions"), **STRETCH):
        return
    try:
        import pypdf, pytesseract, platform
        from pdf2image import convert_from_bytes
        from PIL import Image
    except ImportError as e:
        st.error(trf("Importer needs extra packages: {0}. See requirements.txt.", e))
        return
    if platform.system() == "Windows":
        pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    with st.spinner(tr("Extracting and structuring text…")):
        try:
            data, text = up.getvalue(), ""
            if up.name.lower().endswith(".pdf"):
                for page in pypdf.PdfReader(io.BytesIO(data)).pages:
                    text += (page.extract_text() or "") + "\n"
                if not text.strip():
                    text = "\n".join(pytesseract.image_to_string(img) for img in convert_from_bytes(data))
            else:
                text = pytesseract.image_to_string(Image.open(io.BytesIO(data)))
            if not text.strip():
                st.error(tr("OCR could not extract readable text."))
                return
            added = 0
            for block in re.split(r"\n\s*(?=\d+[.)]\s)", text):
                block = block.strip()
                if not block:
                    continue
                m = re.match(r"(\d+)[.)]\s+", block)
                number = store.free_number(m.group(1) if m else None)
                store.add_question({"number": number, "identifier": "", "type": itype,
                                    "question": block[m.end():] if m else block, "options": [],
                                    "answer": "Faculty review guideline.", "max_marks": float(default_marks)})
                added += 1
            ss["form_success"] = f"Imported {added} questions ({default_marks:g} marks each) — review their numbers and marks below."
            st.rerun()
        except Exception as e:  # noqa: BLE001 - show any OCR/PDF failure to the teacher
            st.error(trf("Import error: {0}", e))


def render_creator(store):
    banner(tr("✍️ Question Creator Studio"), trf("{0} — numbering, weightage, editing and import", store.dept))
    _flash()
    _add_section(store)
    st.markdown("---")
    qs = _bank_overview(store)
    st.markdown("---")
    _edit_section(store, qs)
    st.markdown("---")
    _import_section(store)


# ======================================================================
# VIEWS/EVALUATION — Teacher evaluation & marking dashboard + report-card finalisation.
# ======================================================================
STATUS = {"submitted": "PENDING ⏳", "in_review": "IN REVIEW ✏️", "finalized": "FINALISED ✅"}


def _show_files(store, sub, qid, files):
    for slot, f in files.items():
        data = store.read_upload(f.get("path", ""))
        label = "Code file" if slot == "code_file" else "Document / image"
        st.markdown(f"📎 **{label}:** `{f['name']}`")
        if data is None:
            st.warning(tr("File is missing in storage."))
            continue
        low = f["name"].lower()
        if low.endswith((".png", ".jpg", ".jpeg")):
            try:
                st.image(data, width=520)
            except Exception:  # corrupt / unreadable image
                st.warning(tr("Preview not available — use the download button."))
        elif low.endswith((".py", ".txt")):
            st.code(data.decode("utf-8", errors="replace")[:20000], language="python")
        st.download_button(trf("📥 Download {0}", f['name']), data, file_name=f["name"],
                           key=f"dl_{sub['submission_id']}_{qid}_{slot}")


def _answer_block(store, sub, q):
    a = sub["answers"].get(str(q["id"]), {})
    if q["type"] == "mcq":
        ok = a.get("choice") == q["answer"]
        key = q["answer"]
        if ok:
            st.success(trf("Student choice: **{0}** — Correct ✅", a.get('choice')))
        else:
            st.error(trf("Student choice: **{0}** — Incorrect ❌ · Key: **{1}**", a.get('choice'), key))
        return
    if a.get("text", "").strip():
        st.info(trf("**Typed answer**\n\n{0}", a['text']))
    if a.get("code", "").strip():
        st.markdown(tr("**Submitted code (never executed):**"))
        st.code(a["code"], language="python")
    if not a.get("files") and not a.get("text", "").strip() and not a.get("code", "").strip():
        st.warning(tr("No answer provided."))
    _show_files(store, sub, q["id"], a.get("files", {}))
    st.caption(trf("Model key / rubric: {0}", q['answer'] or '—'))


def _collect_marks(sub):
    marks = dict(sub.get("marks", {}))
    remarks = dict(sub.get("remarks", {}))
    sid = sub["submission_id"]
    for q in sub["paper"]:
        if q["type"] == "mcq":
            continue
        qid = str(q["id"])
        marks[qid] = float(ss.get(f"mark_{sid}_{qid}", marks.get(qid, 0.0)))
        remarks[qid] = ss.get(f"remark_{sid}_{qid}", remarks.get(qid, ""))
    return marks, remarks, ss.get(f"feedback_{sid}", sub.get("overall_feedback", ""))


def _save(store, sub, finalize, user):
    marks, remarks, feedback = _collect_marks(sub)
    updates = {"marks": marks, "remarks": remarks, "overall_feedback": feedback, "status": "in_review"}
    if finalize:
        updates.update(status="finalized", evaluated_by=user["username"], evaluated_at=now_str())
    new = store.update_submission(sub["submission_id"], updates)
    if finalize:
        audit("evaluation_finalized", user["username"], f"{store.dept}/{sub['submission_id']}")
        try:
            store.save_report(sub["submission_id"], build_report_pdf(new, store.dept))
            ss["form_success"] = f"✅ Finalised {sub['submission_id']} — report card generated."
        except ImportError:
            ss["form_success"] = "Finalised, but PDF support (reportlab) is not installed — run: pip install reportlab"
    else:
        ss["form_success"] = f"Progress saved for {sub['submission_id']}."
    st.rerun()


def render_evaluation(store, user):
    banner(tr("👨‍🏫 Evaluation & Marking Dashboard"), trf("{0} — review code and scripts, award marks, issue report cards", store.dept))
    if "form_success" in ss:
        st.success(tr(ss.pop("form_success")))

    subs = store.submissions()
    if not subs:
        st.info(tr("No student submissions yet."))
        return
    test_titles = {}
    for s in subs:
        test_titles[s.get("test_id") or "-"] = s.get("test_title") or "—"
    if len(test_titles) > 1:
        tsel = st.selectbox(tr("Test"), ["all"] + list(test_titles), key=f"ev_test_{lang()}",
                            format_func=lambda i: tr("All tests") if i == "all" else test_titles[i])
        if tsel != "all":
            subs = [s for s in subs if (s.get("test_id") or "-") == tsel]
    counts = {k: sum(s["status"] == k for s in subs) for k in STATUS}
    c1, c2, c3 = st.columns(3)
    c1.metric(tr("Pending"), counts["submitted"])
    c2.metric(tr("In review"), counts["in_review"])
    c3.metric(tr("Finalised"), counts["finalized"])

    flt = st.radio(tr("Show"), ["All", "Pending", "In review", "Finalised"], horizontal=True, format_func=tr)
    want = {"All": None, "Pending": "submitted", "In review": "in_review", "Finalised": "finalized"}[flt]
    shown = [s for s in subs if want is None or s["status"] == want]
    if not shown:
        st.info(tr("Nothing in this category."))
        return
    labels = {f"{s['submission_id']} — {s['student_name']} (Roll {s['roll_no']}) [{tr(STATUS[s['status']])}]"
              + (f" · {s['test_title']}" if s.get("test_title") else "") + (" ⚠️" if s.get("late") else ""): s["submission_id"]
              for s in shown}
    sid = labels[st.selectbox(tr("Select submission"), list(labels))]
    sub = store.get_submission(sid)
    finalized = sub["status"] == "finalized"

    st.markdown(trf("### {0} · Roll {1} · `{2}`", sub['student_name'], sub['roll_no'], sid))
    st.caption(trf("Submitted {0}", sub['timestamp']))
    if sub.get("test_title"):
        st.caption(trf("Assessment: {0}", sub["test_title"]))
    if sub.get("late"):
        st.warning(tr("⚠️ Late submission — it arrived after the deadline."))
    if sub.get("auto_submitted"):
        st.info(tr("⏰ Auto-submitted when the time limit ended."))
    live_marks = _collect_marks(sub)[0] if not finalized else sub["marks"]
    t = totals({**sub, "marks": live_marks})
    m1, m2, m3, m4 = st.columns(4)
    m1.metric(tr("Marks"), f"{t['obtained']:g} / {t['max']:g}")
    m2.metric(tr("Percentage"), f"{t['percent']:.1f}%")
    m3.metric(tr("Grade"), t["grade"])
    m4.metric(tr("Result"), tr("PASS") if t["passed"] else tr("FAIL"))
    st.markdown("---")

    for q in sub["paper"]:
        qid = str(q["id"])
        with st.expander(trf("Q{0} · {1:g} marks · {2}", q["number"], q["max_marks"], q["type"].upper())
                         + (f" · {q['identifier']}" if q.get("identifier") else ""), expanded=True):
            st.markdown(f"**{q['question']}**")
            _answer_block(store, sub, q)
            if q["type"] == "mcq":
                st.caption(trf("Auto-awarded: {0:g} / {1:g}", sub['marks'].get(qid, 0), q['max_marks']))
            elif finalized:
                st.markdown(trf("**Awarded:** {0:g} / {1:g}  \n**Remark:** {2}", sub['marks'].get(qid, 0), q['max_marks'], sub.get('remarks', {}).get(qid) or '—'))
            else:
                a, b = st.columns([1, 3])
                a.number_input(trf("Marks (max {0:g})", q['max_marks']), 0.0, float(q["max_marks"]), step=0.5,
                               value=min(float(sub["marks"].get(qid, 0.0)), float(q["max_marks"])),
                               key=f"mark_{sid}_{qid}")
                b.text_input(tr("Faculty remark"), value=sub.get("remarks", {}).get(qid, ""),
                             placeholder=tr("e.g. Correct logic, missing edge-case handling"), key=f"remark_{sid}_{qid}")

    if finalized:
        st.markdown(trf("**Overall feedback:** {0}", sub.get('overall_feedback') or '—'))
        st.caption(trf("Finalised by {0} on {1}", sub.get('evaluated_by'), sub.get('evaluated_at')))
        _report_download(store, sub)
        if st.button(tr("🔓 Re-open for editing"), **STRETCH):
            store.update_submission(sid, {"status": "in_review"})
            audit("evaluation_reopened", user["username"], f"{store.dept}/{sid}")
            st.rerun()
    else:
        st.text_area(tr("Overall feedback for the student"), value=sub.get("overall_feedback", ""), key=f"feedback_{sid}")
        b1, b2 = st.columns(2)
        if b1.button(tr("💾 Save Progress"), **STRETCH):
            _save(store, sub, False, user)
        if b2.button(tr("✅ Finalise & Generate Report Card"), type="primary", **STRETCH):
            _save(store, sub, True, user)

    with st.expander(tr("⚠️ Danger zone")):
        ok = st.checkbox(tr("I understand this permanently deletes the submission and its files"), key=f"del_ok_{sid}")
        if st.button(tr("🗑️ Delete submission"), disabled=not ok, key=f"del_{sid}"):
            store.delete_submission(sid)
            audit("submission_deleted", user["username"], f"{store.dept}/{sid}")
            st.rerun()


def _report_download(store, sub):
    st.download_button(tr("🖨️ Printable report card — English + বাংলা (HTML)"), build_report_html(sub, store.dept).encode("utf-8"),
                       file_name=f"ReportCard_{sub['submission_id']}.html", mime="text/html", key=f"rch_{sub['submission_id']}", **STRETCH)
    try:
        data = store.load_report(sub["submission_id"]) or build_report_pdf(sub, store.dept)
        st.download_button(tr("📄 Download Report Card (PDF)"), data, file_name=f"ReportCard_{sub['submission_id']}.pdf",
                           mime="application/pdf", key=f"rc_{sub['submission_id']}", **STRETCH)
    except ImportError:
        st.error(tr("Install reportlab to generate PDFs: pip install reportlab"))


# ======================================================================
# VIEWS/ANALYTICS — Performance analytics dashboard (finalised evaluations only).
# ======================================================================
GRADES = [g for _, g, _ in GRADE_SCALE]


def _results_frame(subs):
    rows = []
    for s in subs:
        if s["status"] != "finalized":
            continue
        t = totals(s)
        rows.append({
            "Submission": s["submission_id"], "Roll": s["roll_no"], "Student": s["student_name"],
            "Marks": t["obtained"], "Max": t["max"], "Percent": t["percent"], "Grade": t["grade"],
            "Result": "PASS" if t["passed"] else "FAIL", "Date": s["timestamp"][:10], "Test": s.get("test_title") or "—",
        })
    return pd.DataFrame(rows)


def _question_frame(subs):
    rows = []
    for s in subs:
        if s["status"] != "finalized":
            continue
        for q in s["paper"]:
            got = max(0.0, min(float(s["marks"].get(str(q["id"]), 0) or 0), float(q["max_marks"])))
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
    df_all = _results_frame(subs)
    titles = {}
    for s in subs:
        titles[s.get("test_id") or "-"] = s.get("test_title") or "—"
    if len(titles) > 1:
        tsel = st.selectbox(tr("Test"), ["all"] + list(titles), key=f"an_test_{lang()}",
                            format_func=lambda i: tr("All tests") if i == "all" else titles[i])
        if tsel != "all":
            subs = [s for s in subs if (s.get("test_id") or "-") == tsel]
    df = _results_frame(subs)
    st.markdown(tr("##### 🧭 Evaluation progress"))
    done = len(df)
    st.progress(done / len(subs), text=trf("{0} of {1} submissions finalised", done, len(subs)))
    if df.empty:
        st.info(tr("Analytics appear once at least one evaluation is finalised."))
        return
    _kpis(df, len(subs))

    t_dist, t_q, t_students, t_cmp = st.tabs([tr("📈 Score Distribution"), tr("🧩 Question Analysis"), tr("🏅 Student Records"), tr("📉 Test Comparison")])
    with t_cmp:
        if df_all["Test"].nunique() < 2:
            st.info(tr("Comparison appears once two or more tests have finalised results."))
        else:
            cmp_df = df_all.groupby("Test", sort=False).agg(avg=("Percent", "mean"), first=("Date", "min"), students=("Roll", "count")).sort_values("first")
            st.markdown(tr("**Average score per test (%)**"))
            st.bar_chart(cmp_df["avg"].round(1), color="#ffd400")
            show_df(cmp_df.reset_index().rename(columns={"avg": "Avg %", "first": "Date", "students": "Students"}).round({"Avg %": 1}))
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
        low = df[df["Percent"] < PASS_PERCENT].sort_values("Percent")[["Roll", "Student", "Percent", "Grade"]]
        show_df(low, c2) if len(low) else c2.success(tr("Everyone has passed 🎉"))
        st.markdown(tr("**All finalised results**"))
        show_df(df.sort_values("Percent", ascending=False))
        st.download_button(tr("📥 Download results (CSV)"), df.to_csv(index=False).encode("utf-8-sig"),
                           file_name=f"{store.slug}_results.csv", mime="text/csv")


def _all_departments_view():
    rows = []
    for dept in DEPARTMENTS:
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


def render_analytics(store, user):
    banner(tr("📊 Performance Analytics"), tr("Scores, distributions and progress — restricted to faculty"))
    if user["role"] == "admin":
        t1, t2 = st.tabs([f"🏛️ {dname(store.dept)}", tr("🌐 All Departments")])
        with t1:
            _department_view(store)
        with t2:
            _all_departments_view()
    else:
        _department_view(store)


# ======================================================================
# APP — Departmental Assessment & Grading Portal - entry point.   Run:  streamlit run app.py
# ======================================================================
st.session_state.setdefault("lang", DEFAULT_LANGUAGE)
apply_theme()
apply_admin_reset_secret()
ensure_admin_bootstrap()
try:
    maybe_auto_backup()          # once per session: backs up if the newest backup is old
except StorageError:
    pass

# ---------------------------------------------------------------- session & role
user = current_user()                    # enforces idle timeout
dept = st.session_state.get("dept")
if "flash" in st.session_state:
    st.warning(tr(st.session_state.pop("flash")))


def allowed_pages():
    pages = [P_HOME, P_FAQ, P_REVIEWS]
    if dept:
        pages += [P_TAKE, P_MATERIALS, P_CARD]
    if user is None:
        pages.append(P_LOGIN)
    else:
        if can_manage(user, dept):
            pages += [P_CREATOR, P_TESTS, P_ROSTER, P_UPLOAD, P_EVAL, P_ANALYTICS]
        if is_admin(user):
            pages.append(P_ADMIN)
        pages.append(P_ACCOUNT)
    return pages


pages = allowed_pages()
if user and user.get("must_change"):
    pages = [P_ACCOUNT]                       # forced password change before anything else

# programmatic navigation requested by a previous run
if "_goto" in st.session_state:
    target = st.session_state.pop("_goto")
    if target in pages:
        st.session_state["nav"] = target
if st.session_state.get("nav") not in pages:
    st.session_state["nav"] = pages[0]

# ---------------------------------------------------------------- sidebar
with st.sidebar:
    if os.path.exists("pjc_logo.jpg"):
        st.image("pjc_logo.jpg", width=110)
    st.radio("🌐 Language / ভাষা", list(LANGS), key="lang", format_func=LANGS.get, horizontal=True)
    st.markdown(tr("## 🎓 Portal"))
    stu = current_student(dept) if dept else None
    if user is not None:
        st.markdown(trf("<span class='role-chip'>{0} · {1}</span>", user['role'].upper(), user['username']), unsafe_allow_html=True)
    elif not stu:
        st.markdown(tr("<span class='role-chip student'>STUDENT / GUEST</span>"), unsafe_allow_html=True)
    st.markdown(trf("**Department:** {0}", dept or tr("— not selected —")))
    if stu:
        st.markdown(trf("<span class='role-chip student'>🎓 {0} · {1}</span>", stu["name"], stu["roll"]), unsafe_allow_html=True)
        if st.button(tr("🚪 Student logout"), key="stu_logout"):
            student_logout()
            for k in [k for k in st.session_state if k.startswith("w_") or k.startswith("stu_")]:
                del st.session_state[k]
            st.rerun()
    sidebar_guide(user, dept)
    page = st.radio(tr("Navigate"), pages, key="nav", label_visibility="collapsed", format_func=tr)
    if user:
        st.caption(tr("Session auto-expires after 30 idle minutes."))

# ---------------------------------------------------------------- RBAC gate (defence in depth)
if page in TEACHER_PAGES and not can_manage(user, dept):
    audit("access_denied", user["username"] if user else "student", f"{page} / {dept}")
    st.error(tr("⛔ Access denied. This page is restricted to faculty of the selected department."))
    st.stop()
if page in ADMIN_PAGES and not is_admin(user):
    audit("access_denied", user["username"] if user else "student", page)
    st.error(tr("⛔ Access denied. Administrators only."))
    st.stop()

# ---------------------------------------------------------------- router
try:
    if page == P_HOME:
        render_home()
    elif page == P_FAQ:
        render_faq()
    elif page == P_REVIEWS:
        render_reviews(user)
    elif page == P_LOGIN:
        render_login(dept)
    elif page == P_ACCOUNT and user:
        render_account(user)
    elif page == P_ADMIN:
        render_admin(user)
    elif dept is None:
        st.warning(tr("Please select a department on the Home page first."))
    else:
        store = DeptStore(dept)
        if page == P_TAKE:
            render_assessment(store)
        elif page == P_MATERIALS:
            render_study_materials(store)
        elif page == P_UPLOAD:
            render_materials_manager(store, user)
        elif page == P_TESTS:
            render_tests_manager(store, user)
        elif page == P_ROSTER:
            render_roster_manager(store, user)
        elif page == P_CARD:
            render_report_card(store)
        elif page == P_CREATOR:
            render_creator(store)
        elif page == P_EVAL:
            render_evaluation(store, user)
        elif page == P_ANALYTICS:
            render_analytics(store, user)
except StorageError as e:
    st.error(trf("💾 Storage problem: {0}", e))
    st.info(tr("Check the Supabase keys in Secrets and the setup SQL (Admin Console → Storage & Backup → Test connection)."))
    # ======================================================================
# FOOTER / COPYRIGHT
# ======================================================================
st.markdown(
    """
    <hr style="margin-top: 3rem; margin-bottom: 1rem; opacity: 0.25;">
    <div style="text-align: center; font-size: 0.85rem; opacity: 0.78; padding-bottom: 1rem; line-height: 1.5;">
        &copy; 2026 <strong>Prabhu Jagatbandhu College</strong>. All rights reserved.<br>
        Developed and maintained by <strong>Dr. Kisor Mukhopadhyay</strong>, Associate Professor, Department of Physics.
    </div>
    """,
    unsafe_allow_html=True,
)
