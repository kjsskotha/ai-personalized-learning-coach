import os
import json
import sqlite3
from datetime import datetime

import streamlit as st
from dotenv import load_dotenv
from openai import OpenAI

# =========================================================
# CONFIGURATION
# =========================================================
load_dotenv()
st.set_page_config(
    page_title="AI Personalized Learning Coach",
    page_icon="🎓",
    layout="wide"
)

DB_NAME = "learning_coach.db"
DEFAULT_MODEL = "openai/gpt-oss-120b"


def get_secret(name, default=None):
    value = os.getenv(name)
    if value:
        return value
    try:
        return st.secrets.get(name, default)
    except Exception:
        return default


def ask_ai(prompt):
    api_key = get_secret("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY is missing. Add it in Streamlit Cloud Secrets.")

    client = OpenAI(
        api_key=api_key,
        base_url="https://api.groq.com/openai/v1"
    )
    response = client.chat.completions.create(
        model=get_secret("GROQ_MODEL", DEFAULT_MODEL),
        messages=[
            {
                "role": "system",
                "content": (
                    "You are an educational AI learning coach. "
                    "Create clear, accurate, beginner-friendly learning content. "
                    "Return valid JSON when requested."
                )
            },
            {"role": "user", "content": prompt}
        ],
        temperature=0.3
    )
    result = response.choices[0].message.content
    if not result:
        raise ValueError("The AI returned an empty response.")
    return result.strip()


def extract_json(raw_text):
    raw_text = raw_text.strip()
    if raw_text.startswith("```"):
        lines = raw_text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        raw_text = "\n".join(lines).strip()

    start = raw_text.find("{")
    end = raw_text.rfind("}")
    if start < 0 or end < 0:
        raise ValueError("Invalid JSON response from AI.")
    return json.loads(raw_text[start:end + 1])


# =========================================================
# DATABASE
# =========================================================
def get_connection():
    conn = sqlite3.connect(DB_NAME, timeout=20)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def initialize_database():
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                subject TEXT NOT NULL,
