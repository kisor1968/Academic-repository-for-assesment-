"""English / Bengali interface text.

tr("English text")        -> Bengali when the language switch is on বাংলা (falls back to English)
trf("Hello {0}", name)    -> same, for sentences with values filled in
The Bengali wording lives in translations_bn.py as plain Python dictionaries - easy to review and edit.
"""
import re

import streamlit as st

from . import config
from .translations_bn import BN, BN_PATTERNS, DEPT_BN

LANGS = {"en": "English", "bn": "বাংলা"}


def lang():
    return st.session_state.get("lang", config.DEFAULT_LANGUAGE)


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
