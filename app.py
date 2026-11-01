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

def get_connection():
    connection = sqlite3.connect(DB_NAME, timeout=20)
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database():
    try:
        with get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS learner_profiles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    learner_name TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    learning_goal TEXT NOT NULL,
                    skill_level TEXT NOT NULL,
                    target_days INTEGER NOT NULL,
                    daily_minutes INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS learning_plans (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    profile_id INTEGER NOT NULL,
                    plan_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(profile_id) REFERENCES learner_profiles(id)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS quiz_attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    profile_id INTEGER NOT NULL,
                    subject TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    score INTEGER NOT NULL,
                    total_questions INTEGER NOT NULL,
                    wrong_topics TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(profile_id) REFERENCES learner_profiles(id)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS topic_progress (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    profile_id INTEGER NOT NULL,
                    topic TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'Pending',
                    last_score INTEGER,
                    total_questions INTEGER,
                    updated_at TEXT NOT NULL,
                    UNIQUE(profile_id, topic),
                    FOREIGN KEY(profile_id) REFERENCES learner_profiles(id)
                )
            """)
    except sqlite3.Error as exc:
        st.error(f"Database setup failed: {exc}")
        st.stop()


def save_profile(name, subject, goal, level, days, minutes):
    with get_connection() as conn:
        cursor = conn.execute("""
            INSERT INTO learner_profiles
            (learner_name, subject, learning_goal, skill_level,
             target_days, daily_minutes, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            name, subject, goal, level, days, minutes,
            datetime.now().isoformat(timespec="seconds")
        ))
        return cursor.lastrowid


def update_profile(profile_id, profile):
    with get_connection() as conn:
        conn.execute("""
            UPDATE learner_profiles
            SET learner_name=?, subject=?, learning_goal=?, skill_level=?,
                target_days=?, daily_minutes=?
            WHERE id=?
        """, (
            profile["name"], profile["subject"], profile["goal"],
            profile["level"], profile["days"], profile["minutes"], profile_id
        ))


def save_plan(profile_id, plan):
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO learning_plans (profile_id, plan_json, created_at)
            VALUES (?, ?, ?)
        """, (
            profile_id, json.dumps(plan, ensure_ascii=False),
            datetime.now().isoformat(timespec="seconds")
        ))


def save_attempt(profile_id, subject, topic, score, total, wrong_topics):
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO quiz_attempts
            (profile_id, subject, topic, score, total_questions, wrong_topics, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            profile_id, subject, topic, score, total,
            json.dumps(wrong_topics, ensure_ascii=False),
            datetime.now().isoformat(timespec="seconds")
        ))


def update_topic_progress(profile_id, topic, score, total):
    # A single short quiz is not treated as proof of mastery.
    percentage = round((score / total) * 100) if total else 0
    status = "Needs revision" if percentage < 60 else "In progress"
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO topic_progress
            (profile_id, topic, status, last_score, total_questions, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(profile_id, topic) DO UPDATE SET
                status=excluded.status,
                last_score=excluded.last_score,
                total_questions=excluded.total_questions,
                updated_at=excluded.updated_at
        """, (
            profile_id, topic, status, score, total,
            datetime.now().isoformat(timespec="seconds")
        ))


def set_topic_completed(profile_id, topic):
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO topic_progress
            (profile_id, topic, status, updated_at)
            VALUES (?, ?, 'Completed', ?)
            ON CONFLICT(profile_id, topic) DO UPDATE SET
                status='Completed', updated_at=excluded.updated_at
        """, (profile_id, topic, datetime.now().isoformat(timespec="seconds")))


def load_profiles():
    with get_connection() as conn:
        return conn.execute("""
            SELECT id, learner_name, subject, learning_goal,
                   skill_level, target_days, daily_minutes, created_at
            FROM learner_profiles ORDER BY id DESC
        """).fetchall()


def load_plans(profile_id):
    with get_connection() as conn:
        return conn.execute("""
            SELECT id, plan_json, created_at FROM learning_plans
            WHERE profile_id=? ORDER BY id DESC
        """, (profile_id,)).fetchall()


def load_attempts(profile_id):
    with get_connection() as conn:
        return conn.execute("""
            SELECT subject, topic, score, total_questions, wrong_topics, created_at
            FROM quiz_attempts WHERE profile_id=? ORDER BY id DESC
        """, (profile_id,)).fetchall()


def load_topic_progress(profile_id):
    with get_connection() as conn:
        return conn.execute("""
            SELECT topic, status, last_score, total_questions, updated_at
            FROM topic_progress WHERE profile_id=? ORDER BY topic
        """, (profile_id,)).fetchall()


def load_latest_plan(profile_id):
    plans = load_plans(profile_id)
    if not plans:
        return None
    try:
        return json.loads(plans[0][1])
    except (json.JSONDecodeError, TypeError):
        return None


def profile_from_row(row):
    return {
        "name": row[1],
        "subject": row[2],
        "goal": row[3],
        "level": row[4],
        "days": int(row[5]),
        "minutes": int(row[6])
    }
    # ============================================================
# AI STUDY PLAN GENERATION AND VALIDATION
# ============================================================

def validate_plan(plan, expected_days, daily_minutes):
    if not isinstance(plan, dict) or not isinstance(plan.get("days"), list):
        raise ValueError("The AI did not return a valid day-wise plan.")
    if len(plan["days"]) != expected_days:
        raise ValueError(
            f"The AI returned {len(plan['days'])} days instead of {expected_days}. "
            "Please generate the plan again."
        )

    required_text_fields = ["topic", "practice_task", "revision"]
    for index, day in enumerate(plan["days"], start=1):
        if not isinstance(day, dict):
            raise ValueError(f"Day {index} has an invalid format.")
        for field in required_text_fields:
            if not isinstance(day.get(field), str) or not day[field].strip():
                raise ValueError(f"Day {index} is missing {field}.")
        for field in ["objectives", "activities"]:
            if not isinstance(day.get(field), list) or not day[field]:
                raise ValueError(f"Day {index} is missing {field}.")
        try:
            estimated = int(day.get("estimated_minutes", 0))
        except (TypeError, ValueError):
            estimated = 0
        if estimated <= 0 or estimated > daily_minutes:
            raise ValueError(
                f"Day {index} has an invalid estimated time. "
                "The plan must fit the daily study schedule."
            )
        day["day"] = index
        day["estimated_minutes"] = estimated
    plan.setdefault("overview", "Your personalized learning journey.")
    return plan


def generate_study_plan(profile):
    prompt = f"""
Create a personalized day-wise learning plan as valid JSON.

Learner: {profile['name']}
Subject: {profile['subject']}
Goal: {profile['goal']}
Current level: {profile['level']}
Duration: exactly {profile['days']} days
Available daily study time: {profile['minutes']} minutes

Return this exact JSON structure:
{{
  "overview": "Short description",
  "days": [
    {{
      "day": 1,
      "topic": "Topic name",
      "objectives": ["Objective 1", "Objective 2"],
      "estimated_minutes": 45,
      "activities": ["Activity 1", "Activity 2"],
      "practice_task": "Practical task",
      "revision": "Revision activity"
    }}
  ]
}}

Rules:
- Return exactly {profile['days']} day entries.
- estimated_minutes must be a whole number greater than zero and no more than {profile['minutes']}.
- The estimated time is the total time for that day's learning.
- Include realistic activities and a practice task every day.
- Progress from the learner's current level toward the stated goal.
- Use clear, beginner-friendly language where appropriate.
- Do not claim the learner has mastered a topic.
- Return valid JSON only, with no markdown fences.
"""
    plan = extract_json(ask_ai(prompt))
    return validate_plan(plan, profile["days"], profile["minutes"])


# ============================================================
# AI QUIZ GENERATION AND VALIDATION
# ============================================================

def generate_quiz(subject, topic, level):
    prompt = f"""
Create exactly five multiple-choice questions as valid JSON.

Subject: {subject}
Topic: {topic}
Learner level: {level}

Use this format:
{{
  "questions": [
    {{
      "question": "Question text",
      "options": {{
        "A": "Option A",
        "B": "Option B",
        "C": "Option C",
        "D": "Option D"
      }},
      "answer": "A",
      "explanation": "Explain why the answer is correct",
      "topic": "Specific concept tested"
    }}
  ]
}}

Rules:
- Create exactly five questions.
- Every question must have four non-empty, distinct options A, B, C, D.
- answer must be exactly A, B, C, or D.
- Include a useful explanation and a specific concept for each question.
- Keep every question relevant to the subject, topic, and level.
- Return JSON only, without markdown fences.
"""
    data = extract_json(ask_ai(prompt))
    questions = data.get("questions") if isinstance(data, dict) else None
    if not isinstance(questions, list) or len(questions) != 5:
        raise ValueError("The AI did not generate exactly five questions.")

    for number, question in enumerate(questions, start=1):
        if not isinstance(question, dict):
            raise ValueError(f"Question {number} has an invalid format.")
        options = question.get("options")
        if not isinstance(options, dict):
            raise ValueError(f"Question {number} is missing options.")
        keys = ["A", "B", "C", "D"]
        if not all(isinstance(options.get(k), str) and options[k].strip() for k in keys):
            raise ValueError(f"Question {number} must contain four complete options.")
        if len({options[k].strip().casefold() for k in keys}) != 4:
            raise ValueError(f"Question {number} contains duplicate options.")
        if question.get("answer") not in keys:
            raise ValueError(f"Question {number} has an invalid answer key.")
        if not isinstance(question.get("question"), str) or not question["question"].strip():
            raise ValueError(f"Question {number} has no question text.")
        question.setdefault("explanation", "Review this concept and try again.")
        question.setdefault("topic", topic)
    return questions


# ============================================================
# SESSION STATE AND NAVIGATION
# ============================================================

def go_to_quiz():
    st.session_state["navigation_page"] = "📝 Practice Quiz"


def clear_quiz():
    st.session_state.quiz_questions = None
    st.session_state.quiz_submitted = False
    st.session_state.quiz_result = None
    st.session_state.quiz_topic = ""


for key, default in {
    "profile_id": None,
    "profile": None,
    "current_plan": None,
    "quiz_questions": None,
    "quiz_topic": "",
    "quiz_submitted": False,
    "quiz_result": None
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

initialize_database()

st.sidebar.title("🎓 Learning Coach")
st.sidebar.caption("Your personal AI-powered study companion")
page = st.sidebar.radio(
    "Navigate",
    [
        "🏠 Home & Study Plan",
        "📝 Practice Quiz",
        "📊 Progress Dashboard"
    ],
    key="navigation_page"
)
st.sidebar.divider()

# Restore an existing saved profile after an app refresh/restart.
try:
    saved_profiles = load_profiles()
except sqlite3.Error as error:
    st.error(f"Could not read learner profiles from the database: {error}")
    saved_profiles = []

if saved_profiles:
    labels = {
        f"{row[1]} — {row[2]} (Profile {row[0]})": row
        for row in saved_profiles
    }
    label_list = list(labels.keys())
    current_label = next(
        (label for label, row in labels.items()
         if row[0] == st.session_state.profile_id),
        label_list[0]
    )
    chosen_label = st.sidebar.selectbox(
        "Load saved learner",
        label_list,
        index=label_list.index(current_label)
    )
    if st.sidebar.button("Load Selected Learner"):
        chosen_row = labels[chosen_label]
        st.session_state.profile_id = chosen_row[0]
        st.session_state.profile = profile_from_row(chosen_row)
        st.session_state.current_plan = load_latest_plan(chosen_row[0])
        clear_quiz()
        st.sidebar.success("Saved learner loaded.")

if st.session_state.profile:
    st.sidebar.success(f"Active learner: {st.session_state.profile['name']}")
else:
    st.sidebar.info("Create or load a learner profile to get started.")


# ============================================================
# HOME AND STUDY PLAN
# ============================================================

if page == "🏠 Home & Study Plan":
    st.title("🎓 AI Personalized Learning Coach")
        st.write(
        "Create a personalized study plan, practise quizzes, understand "
        "your mistakes, and track your learning progress."
    )

    st.subheader("1. Set Up or Update Your Learning Profile")
    active = st.session_state.profile or {}
    with st.form("profile_form"):
        name = st.text_input("Learner name", value=active.get("name", ""))
        subject = st.text_input("Subject", value=active.get("subject", ""))
        goal = st.text_area("Learning goal", value=active.get("goal", ""))
        levels = ["Beginner", "Intermediate", "Advanced"]
        default_level = active.get("level", "Beginner")
        level = st.selectbox(
            "Current skill level",
            levels,
            index=levels.index(default_level) if default_level in levels else 0
        )
        col1, col2 = st.columns(2)
        with col1:
            days = st.number_input(
                "Target duration (days)", min_value=1, max_value=90,
                value=int(active.get("days", 7))
            )
        with col2:
            minutes = st.number_input(
                "Daily study time (minutes)", min_value=10, max_value=480,
                value=int(active.get("minutes", 60)), step=5
            )
        submitted = st.form_submit_button(
            "Create / Update and Generate Study Plan",
            type="primary"
        )

    if submitted:
        if not name.strip() or not subject.strip() or not goal.strip():
            st.error("Please complete your name, subject, and learning goal.")
        else:
            profile = {
                "name": name.strip(),
                "subject": subject.strip(),
                "goal": goal.strip(),
                "level": level,
                "days": int(days),
                "minutes": int(minutes)
            }
            with st.spinner("Creating your personalized study plan..."):
                try:
                    plan = generate_study_plan(profile)
                    if st.session_state.profile_id:
                        update_profile(st.session_state.profile_id, profile)
                        profile_id = st.session_state.profile_id
                    else:
                        profile_id = save_profile(
                            profile["name"], profile["subject"], profile["goal"],
                            profile["level"], profile["days"], profile["minutes"]
                        )
                    save_plan(profile_id, plan)
                    st.session_state.profile = profile
                    st.session_state.profile_id = profile_id
                    st.session_state.current_plan = plan
                    clear_quiz()
                    st.success("Your study plan has been saved successfully.")
                except (sqlite3.Error, ValueError, RuntimeError, Exception) as error:
                    st.error(f"Could not create or save the study plan: {error}")
                    st.info(
                        "Check your internet connection and Groq API key, then "
                        "try again. Your previous saved plan is not intentionally deleted."
                    )

    if st.session_state.profile and st.session_state.current_plan:
        profile = st.session_state.profile
        plan = st.session_state.current_plan
        st.divider()
        st.subheader("2. Your Personalized Learning Plan")
        st.write(f"**Learner:** {profile['name']}")
        st.write(f"**Subject:** {profile['subject']}")
        st.write(f"**Goal:** {profile['goal']}")
        st.write(f"**Level:** {profile['level']}")
        st.write(
            f"**Schedule:** {profile['days']} days · "
            f"{profile['minutes']} minutes per day"
        )
        st.info(plan.get("overview", "Your learning journey starts here."))

        try:
            progress_rows = load_topic_progress(st.session_state.profile_id)
            progress_map = {row[0]: row[1] for row in progress_rows}
        except sqlite3.Error:
            progress_map = {}

        for item in plan.get("days", []):
            topic_name = item["topic"]
            status = progress_map.get(topic_name, "Pending")
            with st.expander(
                f"Day {item['day']}: {topic_name} — {status}"
            ):
                st.write(f"**Estimated time:** {item['estimated_minutes']} minutes")
                st.markdown("**Learning objectives**")
                for objective in item["objectives"]:
                    st.write(f"- {objective}")
                st.markdown("**Activities**")
                for activity in item["activities"]:
                    st.write(f"- {activity}")
                st.markdown("**Practice task**")
                st.write(item["practice_task"])
                st.markdown("**Revision**")
                st.write(item["revision"])
                if status != "Completed":
                    if st.button(
                        f"Mark '{topic_name}' as completed",
                        key=f"complete_{st.session_state.profile_id}_{item['day']}"
                    ):
                        try:
                            set_topic_completed(st.session_state.profile_id, topic_name)
                            st.success(f"{topic_name} marked as completed.")
                            st.rerun()
                        except sqlite3.Error as error:
                            st.error(f"Could not update topic progress: {error}")

        st.download_button(
            "Download Study Plan (JSON)",
            data=json.dumps(plan, indent=2, ensure_ascii=False),
            file_name="personalized_study_plan.json",
            mime="application/json"
        )
        st.button("Start a Practice Quiz", type="primary", on_click=go_to_quiz)

    elif st.session_state.profile and not st.session_state.current_plan:
        st.info("No saved plan was found. Generate a new plan using the form above.")


# ============================================================
# PRACTICE QUIZ
# ============================================================

elif page == "📝 Practice Quiz":
    st.title("📝 Topic-Based Practice Quiz")
    st.write(
        "Choose a topic from your plan or enter another topic. "
        "Python calculates your score using the AI-provided answer key."
    )

    if not st.session_state.profile:
        st.warning("Please create or load a learner profile first.")
    else:
        profile = st.session_state.profile
        st.write(f"**Subject:** {profile['subject']} · **Level:** {profile['level']}")

        plan_topics = []
        if st.session_state.current_plan:
            plan_topics = [
                item.get("topic", "")
                for item in st.session_state.current_plan.get("days", [])
                if item.get("topic")
            ]

        if plan_topics:
            selected_plan_topic = st.selectbox(
                "Select a topic from your study plan",
                ["Choose a planned topic"] + plan_topics
            )
        else:
            selected_plan_topic = "Choose a planned topic"

        other_topic = st.text_input(
            "Or enter another topic",
            placeholder="Example: Python loops"
        )
        chosen_topic = (
            other_topic.strip()
            if other_topic.strip()
            else (
                selected_plan_topic
                if selected_plan_topic != "Choose a planned topic"
                else ""
            )
        )

        if st.button("Generate 5 Questions", type="primary"):
            if not chosen_topic:
                st.warning("Please select or enter a topic first.")
            else:
                with st.spinner("Preparing your quiz..."):
                    try:
                        questions = generate_quiz(
                            profile["subject"], chosen_topic, profile["level"]
                        )
                        st.session_state.quiz_questions = questions
                        st.session_state.quiz_topic = chosen_topic
                        st.session_state.quiz_submitted = False
                        st.session_state.quiz_result = None
                        st.rerun()
                    except Exception as error:
                        st.error(f"Could not generate the quiz: {error}")
                        st.info("Please check the API connection and try again.")

        questions = st.session_state.quiz_questions
        if questions:
            st.divider()
            st.subheader(f"Quiz: {st.session_state.quiz_topic}")
            if not st.session_state.quiz_submitted:
                with st.form("quiz_form"):
                    answers = []
                    for index, question in enumerate(questions):
                        st.markdown(
                            f"**Question {index + 1}: {question['question']}**"
                        )
                        options = question["options"]
                        choice = st.radio(
                            f"Choose your answer for Question {index + 1}",
                            options=["A", "B", "C", "D"],
                            format_func=lambda key, opts=options: f"{key}. {opts[key]}",
                            key=f"answer_{index}"
                        )
                        answers.append(choice)
                    quiz_submit = st.form_submit_button("Submit Quiz", type="primary")

                if quiz_submit:
                    score = 0
                    wrong_topics = []
                    results = []
                    for index, question in enumerate(questions):
                        selected = answers[index]
                        correct = question["answer"]
                        is_correct = selected == correct
                        if is_correct:
                            score += 1
                        else:
                            wrong_topics.append(question.get("topic", st.session_state.quiz_topic))
                        results.append({
                            "question": question["question"],
                            "selected": selected,
                            "correct": correct,
                            "options": question["options"],
                            "is_correct": is_correct,
                            "explanation": question.get("explanation", ""),
                            "topic": question.get("topic", st.session_state.quiz_topic)
                        })
                                            try:
                        save_attempt(
                            st.session_state.profile_id,
                            profile["subject"],
                            st.session_state.quiz_topic,
                            score,
                            len(questions),
                            wrong_topics
                        )
                        update_topic_progress(
                            st.session_state.profile_id,
                            st.session_state.quiz_topic,
                            score,
                            len(questions)
                        )
                    except sqlite3.Error as error:
                        st.error(f"Your result was calculated but could not be saved: {error}")
                        st.stop()

                    st.session_state.quiz_result = {
                        "score": score,
                        "total": len(questions),
                        "results": results,
                        "wrong_topics": wrong_topics
                    }
                    st.session_state.quiz_submitted = True
                    st.rerun()

            if st.session_state.quiz_submitted and st.session_state.quiz_result:
                result = st.session_state.quiz_result
                score = result["score"]
                total = result["total"]
                percentage = round((score / total) * 100) if total else 0
                st.subheader("Your Quiz Results")
                st.metric("Score", f"{score}/{total}")
                st.progress(percentage / 100)
                st.write(f"**Accuracy:** {percentage}%")

                if percentage >= 80:
                    st.success(
                        "Strong result on this attempt. Continue practising and "
                        "try the next topic; this short quiz alone does not prove mastery."
                    )
                elif percentage >= 60:
                    st.info("Good effort. Review the explanations and practise again.")
                else:
                    st.warning("This topic needs more revision before moving forward.")

                st.subheader("Answer Review")
                for index, item in enumerate(result["results"]):
                    status = "Correct" if item["is_correct"] else "Needs review"
                    with st.expander(f"Question {index + 1}: {status}"):
                        st.write(item["question"])
                        st.write(
                            f"**Your answer:** {item['selected']}. "
                            f"{item['options'][item['selected']]}"
                        )
                        st.write(
                            f"**Correct answer:** {item['correct']}. "
                            f"{item['options'][item['correct']]}"
                        )
                        st.write(f"**Explanation:** {item['explanation']}")
                        st.write(f"**Concept:** {item['topic']}")

                st.subheader("Personalized Next Steps")
                if result["wrong_topics"]:
                    st.write("**Recommended revision topics:**")
                    for weak in sorted(set(result["wrong_topics"])):
                        st.write(f"- {weak}")
                    st.write("Revise these concepts, then attempt another quiz.")
                else:
                    st.write("You answered all questions correctly in this attempt.")
                    if st.session_state.current_plan:
                        topics = [
                            item["topic"]
                            for item in st.session_state.current_plan.get("days", [])
                        ]
                        current_index = next(
                            (i for i, value in enumerate(topics)
                             if value.casefold() == st.session_state.quiz_topic.casefold()),
                            None
                        )
                        if current_index is not None and current_index + 1 < len(topics):
                            st.write(f"**Suggested next topic:** {topics[current_index + 1]}")
                        else:
                            st.write("Try a more advanced practice topic related to your goal.")

                if st.button("Try Another Quiz"):
                    clear_quiz()
                    st.rerun()


# ============================================================
# PROGRESS DASHBOARD
# ============================================================

elif page == "📊 Progress Dashboard":
    st.title("📊 Learning Progress Dashboard")
    st.write("Review saved plans, completed topics, quiz scores, and next actions.")

    try:
        profiles = load_profiles()
    except sqlite3.Error as error:
        st.error(f"Could not load learner profiles: {error}")
        profiles = []

    if not profiles:
        st.info("No learner profiles found. Create a study plan on the Home page.")
    else:
        profile_options = {
            f"{row[1]} — {row[2]} (Profile {row[0]})": row[0]
            for row in profiles
        }
        selected_label = st.selectbox(
            "Choose a learner profile", list(profile_options.keys())
        )
        selected_id = profile_options[selected_label]
        selected_profile_row = next(row for row in profiles if row[0] == selected_id)
        selected_profile = profile_from_row(selected_profile_row)

        # Load selected profile into session so the learner can continue after refresh.
        if st.button("Use This Profile for Practice"):
            st.session_state.profile_id = selected_id
            st.session_state.profile = selected_profile
            st.session_state.current_plan = load_latest_plan(selected_id)
            clear_quiz()
            st.success("Profile loaded. Open Practice Quiz to continue.")

        col1, col2, col3 = st.columns(3)
        col1.metric("Target Days", selected_profile["days"])
        col2.metric("Daily Study Time", f"{selected_profile['minutes']} min")
        col3.metric("Current Level", selected_profile["level"])
        st.write(f"**Learning goal:** {selected_profile['goal']}")

        try:
            plans = load_plans(selected_id)
            attempts = load_attempts(selected_id)
            progress_rows = load_topic_progress(selected_id)
        except sqlite3.Error as error:
            st.error(f"Could not load dashboard data: {error}")
            plans, attempts, progress_rows = [], [], []

        st.subheader("Topic Progress")
        plan_for_dashboard = None
        if plans:
            try:
                plan_for_dashboard = json.loads(plans[0][1])
            except (json.JSONDecodeError, TypeError):
                st.warning("The latest saved plan could not be read.")

        if plan_for_dashboard:
            progress_map = {row[0]: row[1] for row in progress_rows}
            topic_rows = []
            for day_item in plan_for_dashboard.get("days", []):
                topic_name = day_item.get("topic", "Topic")
                topic_rows.append({
                    "Day": day_item.get("day", ""),
                    "Topic": topic_name,
                    "Status": progress_map.get(topic_name, "Pending")
                })
            st.dataframe(topic_rows, use_container_width=True, hide_index=True)
            completed_count = sum(1 for item in topic_rows if item["Status"] == "Completed")
            pending_count = len(topic_rows) - completed_count
            c1, c2 = st.columns(2)
            c1.metric("Completed Topics", completed_count)
            c2.metric("Pending / In-progress Topics", pending_count)
            next_topic = next(
                (item["Topic"] for item in topic_rows
                 if item["Status"] != "Completed"),
                None
            )
            if next_topic:
                st.info(f"**Next study action:** Continue with {next_topic}.")
            else:
                st.success("All topics in this plan are marked completed.")
        else:
            st.info("Generate a study plan to see topic completion status.")

        st.subheader("Quiz Performance")
        if attempts:
            total_quizzes = len(attempts)
            total_questions = sum(row[3] for row in attempts)
            total_correct = sum(row[2] for row in attempts)
            accuracy = round((total_correct / total_questions) * 100) if total_questions else 0
            c1, c2, c3 = st.columns(3)
            c1.metric("Quizzes Completed", total_quizzes)
            c2.metric("Questions Answered", total_questions)
            c3.metric("Overall Accuracy", f"{accuracy}%")
            st.progress(accuracy / 100)

            st.markdown("### Recent Quiz Attempts")
            for subject_name, topic_name, score, total, wrong_json, created_at in attempts[:10]:
                with st.expander(f"{topic_name} — {score}/{total} ({created_at})"):
                    st.write(f"**Subject:** {subject_name}")
                    st.write(f"**Score:** {score}/{total}")
                    try:
                        weak_topics = json.loads(wrong_json)
                    except (json.JSONDecodeError, TypeError):
                        weak_topics = []
                    if weak_topics:
                        st.write("**Concepts to review:**")
                        for weak in sorted(set(weak_topics)):
                            st.write(f"- {weak}")
                    else:
                        st.write("No incorrect answers in this attempt.")

            chart_rows = [
                {
                    "Quiz": f"{row[1]} ({index + 1})",
                    "Accuracy (%)": round((row[2] / row[3]) * 100) if row[3] else 0
                }
                for index, row in enumerate(reversed(attempts))
            ]
            st.markdown("### Quiz Accuracy Over Time")
            st.line_chart(chart_rows, x="Quiz", y="Accuracy (%)")
        else:
            st.info("Complete a practice quiz to see your score history.")

        if progress_rows:
            st.subheader("Topics Needing Revision")
            revision_topics = [row[0] for row in progress_rows if row[1] == "Needs revision"]
            if revision_topics:
                for topic_name in revision_topics:
                    st.write(f"- {topic_name}")
            else:
                st.write("No topics are currently flagged for revision.")


# ============================================================
# FOOTER
# ============================================================

st.divider()
st.caption(
    "AI Personalized Learning Coach | Python • Streamlit • Groq API • SQLite"
)
st.caption(
    "AI-generated educational content may contain errors. "
    "Quiz results are learning signals, not proof of mastery."
)
