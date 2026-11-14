"""Central settings. Edit DEPARTMENTS / INSTITUTION_NAME / GRADE_SCALE to suit your college."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
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
