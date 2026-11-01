import os
import json
import sqlite3
from datetime import datetime

import streamlit as st
from dotenv import load_dotenv
from openai import OpenAI

# ============================================================
# CONFIGURATION
# ============================================================

load_dotenv()

st.set_page_config(
    page_title="AI Personalized Learning Coach",
    page_icon="🎓",
    layout="wide"
)

DB_NAME = "learning_coach.db"
MODEL_NAME = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")


def get_config(name, default=None):
    value = os.getenv(name)
    if value:
        return value
    try:
        return st.secrets.get(name, default)
    except Exception:
        return default


def get_ai_client():
    api_key = get_config("GROQ_API_KEY")
    if not api_key:
        raise ValueError(
            "GROQ_API_KEY is missing. Add it to your local .env file "
            "or Streamlit Community Cloud Secrets."
        )
    return OpenAI(
        api_key=api_key,
        base_url="https://api.groq.com/openai/v1"
    )


def ask_ai(prompt):
    client = get_ai_client()
    model = get_config("GROQ_MODEL", MODEL_NAME)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are an educational AI learning coach. "
                    "Create accurate, clear, level-appropriate learning content. "
                    "When JSON is requested, return valid JSON only, without markdown."
                )
            },
            {"role": "user", "content": prompt}
        ],
        temperature=0.3
    )
    content = response.choices[0].message.content
    if not content or not content.strip():
        raise ValueError("The AI returned an empty response.")
    return content.strip()


def extract_json(raw_text):
    text = raw_text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("The AI response did not contain valid JSON.")
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError("The AI returned incorrectly formatted JSON. Please retry.") from exc


# ============================================================
# DATABASE AND SAFE DATABASE OPERATIONS
# ============================================================
