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
                goal TEXT NOT NULL,
                level TEXT NOT NULL,
                days INTEGER NOT NULL,
                daily_minutes INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_id INTEGER NOT NULL,
                plan_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(profile_id) REFERENCES profiles(id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS quiz_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_id INTEGER NOT NULL,
                subject TEXT NOT NULL,
                topic TEXT NOT NULL,
                score INTEGER NOT NULL,
                total INTEGER NOT NULL,
                wrong_topics TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(profile_id) REFERENCES profiles(id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS topic_progress (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_id INTEGER NOT NULL,
                topic TEXT NOT NULL,
                status TEXT NOT NULL,
                score INTEGER,
                total INTEGER,
                updated_at TEXT NOT NULL,
                UNIQUE(profile_id, topic),
                FOREIGN KEY(profile_id) REFERENCES profiles(id)
            )
        """)


def save_profile(profile):
    """Always insert a separate learner profile; never overwrite another learner."""
    with get_connection() as conn:
        cursor = conn.execute("""
            INSERT INTO profiles
            (name, subject, goal, level, days, daily_minutes, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            profile["name"], profile["subject"], profile["goal"],
            profile["level"], profile["days"], profile["minutes"],
            datetime.now().isoformat(timespec="seconds")
        ))
        return cursor.lastrowid


def get_profiles():
    with get_connection() as conn:
        return conn.execute("""
            SELECT id, name, subject, goal, level, days, daily_minutes
            FROM profiles ORDER BY id DESC
        """).fetchall()


def save_plan(profile_id, plan):
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO plans (profile_id, plan_json, created_at)
            VALUES (?, ?, ?)
        """, (
            profile_id,
            json.dumps(plan, ensure_ascii=False),
            datetime.now().isoformat(timespec="seconds")
        ))


def get_latest_plan(profile_id):
    with get_connection() as conn:
        row = conn.execute("""
            SELECT plan_json FROM plans
            WHERE profile_id=? ORDER BY id DESC LIMIT 1
        """, (profile_id,)).fetchone()
    if not row:
        return None
    try:
        return json.loads(row[0])
    except (json.JSONDecodeError, TypeError):
        return None


def save_quiz_attempt(profile_id, subject, topic, score, total, wrong_topics):
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO quiz_attempts
            (profile_id, subject, topic, score, total, wrong_topics, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            profile_id, subject, topic, score, total,
            json.dumps(wrong_topics),
            datetime.now().isoformat(timespec="seconds")
        ))


def update_topic_progress(profile_id, topic, score, total):
    percentage = (score / total) * 100 if total else 0
    status = "Needs revision" if percentage < 60 else "In progress"
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO topic_progress
            (profile_id, topic, status, score, total, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(profile_id, topic) DO UPDATE SET
                status=excluded.status,
                score=excluded.score,
                total=excluded.total,
                updated_at=excluded.updated_at
        """, (
            profile_id, topic, status, score, total,
            datetime.now().isoformat(timespec="seconds")
        ))


def mark_topic_completed(profile_id, topic):
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO topic_progress
            (profile_id, topic, status, updated_at)
            VALUES (?, ?, 'Completed', ?)
            ON CONFLICT(profile_id, topic) DO UPDATE SET
                status='Completed', updated_at=excluded.updated_at
        """, (profile_id, topic, datetime.now().isoformat(timespec="seconds")))


def get_topic_progress(profile_id):
    with get_connection() as conn:
        return conn.execute("""
            SELECT topic, status, score, total, updated_at
            FROM topic_progress WHERE profile_id=? ORDER BY topic
        """, (profile_id,)).fetchall()
def get_quiz_attempts(profile_id):
    with get_connection() as conn:
        return conn.execute("""
            SELECT subject, topic, score, total, wrong_topics, created_at
            FROM quiz_attempts WHERE profile_id=? ORDER BY id DESC
        """, (profile_id,)).fetchall()


# =========================================================
# AI STUDY PLAN AND QUIZ
# =========================================================
def generate_study_plan(profile):
    prompt = f"""
Create a personalized study plan as valid JSON.
Learner: {profile['name']}
Subject: {profile['subject']}
Goal: {profile['goal']}
Level: {profile['level']}
Duration: exactly {profile['days']} days
Daily available time: {profile['minutes']} minutes

Return this structure:
{{
  "overview": "Short description",
  "days": [
    {{
      "day": 1,
      "topic": "Topic name",
      "objectives": ["Objective 1", "Objective 2"],
      "estimated_minutes": 45,
      "activities": ["Activity 1", "Activity 2"],
      "practice_task": "Practice task",
      "revision": "Revision activity"
    }}
  ]
}}
Rules:
- Return exactly {profile['days']} days.
- Estimated minutes must be positive and not exceed {profile['minutes']}.
- Include objectives, activities, practice task and revision.
- Arrange topics in a logical order and use simple language.
- Return JSON only.
"""
    data = extract_json(ask_ai(prompt))
    days = data.get("days") if isinstance(data, dict) else None
    if not isinstance(days, list) or len(days) != profile["days"]:
        raise ValueError("The AI did not return the requested number of days.")

    for index, day in enumerate(days, start=1):
        for field in (
            "topic", "objectives", "activities",
            "practice_task", "revision", "estimated_minutes"
        ):
            if field not in day:
                raise ValueError(f"Day {index} is missing {field}.")
        if not isinstance(day["topic"], str) or not day["topic"].strip():
            raise ValueError(f"Day {index} has an invalid topic.")
        if not isinstance(day["objectives"], list) or not isinstance(day["activities"], list):
            raise ValueError(f"Day {index} has invalid objectives or activities.")
        minutes = int(day["estimated_minutes"])
        if minutes <= 0 or minutes > profile["minutes"]:
            raise ValueError(f"Day {index} has an invalid time estimate.")
        day["day"] = index
        day["estimated_minutes"] = minutes

    data.setdefault("overview", "Your personalized learning journey.")
    return data


def generate_quiz(subject, topic, level):
    prompt = f"""
Create exactly 5 multiple-choice questions.
Subject: {subject}
Topic: {topic}
Level: {level}
Return valid JSON:
{{
  "questions": [
    {{
      "question": "Question text",
      "options": {{"A":"Option A","B":"Option B","C":"Option C","D":"Option D"}},
      "answer": "A",
      "explanation": "Explanation",
      "topic": "Concept tested"
    }}
  ]
}}
Rules: exactly 5 questions, four non-empty options each, one correct answer,
answer must be A/B/C/D, include explanations, return JSON only.
"""
    data = extract_json(ask_ai(prompt))
    questions = data.get("questions") if isinstance(data, dict) else None
    if not isinstance(questions, list) or len(questions) != 5:
        raise ValueError("The AI did not generate exactly five questions.")

    for number, question in enumerate(questions, start=1):
        options = question.get("options")
        if not isinstance(options, dict):
            raise ValueError(f"Question {number} has invalid options.")
        for key in ("A", "B", "C", "D"):
            if not isinstance(options.get(key), str) or not options[key].strip():
                raise ValueError(f"Question {number} is missing option {key}.")
        if question.get("answer") not in ("A", "B", "C", "D"):
            raise ValueError(f"Question {number} has an invalid answer.")
        if not question.get("question"):
            raise ValueError(f"Question {number} is empty.")
        question.setdefault("explanation", "Review this concept.")
        question.setdefault("topic", topic)
    return questions


# =========================================================
# SESSION STATE
# =========================================================
def clear_quiz():
    st.session_state.quiz_questions = None
    st.session_state.quiz_result = None
    st.session_state.quiz_submitted = False
    st.session_state.quiz_topic = ""


def load_profile(row):
    st.session_state.profile_id = row[0]
    st.session_state.profile = {
        "name": row[1], "subject": row[2], "goal": row[3],
        "level": row[4], "days": row[5], "minutes": row[6]
    }
    st.session_state.current_plan = get_latest_plan(row[0])
    clear_quiz()


defaults = {
    "profile_id": None,
    "profile": None,
    "current_plan": None,
    "quiz_questions": None,
    "quiz_result": None,
    "quiz_submitted": False,
    "quiz_topic": ""
}
for key, value in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = value

try:
    initialize_database()
except sqlite3.Error as error:
    st.error(f"Database initialization failed: {error}")
    st.stop()


# =========================================================
# SIDEBAR
# =========================================================
st.sidebar.title("🎓 Learning Coach")
st.sidebar.write("Your AI-powered study companion")
page = st.sidebar.radio(
    "Choose a page",
    ["Home & Study Plan", "Practice Quiz", "Progress Dashboard"]
)
st.sidebar.divider()

try:
    saved_profiles = get_profiles()
except sqlite3.Error as error:
    st.error(f"Could not load profiles: {error}")
    saved_profiles = []

if saved_profiles:
    profile_labels = {
        f"{row[1]} - {row[2]} (ID: {row[0]})": row
        for row in saved_profiles
    }
    selected_label = st.sidebar.selectbox(
        "Saved Learner Profiles", list(profile_labels.keys())
    )
    if st.sidebar.button("Load Profile"):
        load_profile(profile_labels[selected_label])
        st.rerun()

if st.session_state.profile:
    st.sidebar.success(f"Active learner: {st.session_state.profile['name']}")
else:
    st.sidebar.info("Create a learner profile to begin.")
# =========================================================
# PROFILE AND STUDY PLAN DISPLAY HELPERS
# =========================================================
def show_profile_details(profile):
    st.subheader("Learner Profile")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.write("**Name:**", profile["name"])
        st.write("**Subject:**", profile["subject"])
    with col2:
        st.write("**Goal:**", profile["goal"])
        st.write("**Level:**", profile["level"])
    with col3:
        st.write("**Study duration:**", f"{profile['days']} days")
        st.write("**Daily study time:**", f"{profile['minutes']} minutes")


def show_study_plan(profile_id):
    plan = get_latest_plan(profile_id)
    st.subheader("Your Study Plan")
    if not plan:
        st.info("No study plan has been generated for this learner yet.")
        return

    if plan.get("overview"):
        st.write(plan["overview"])

    for day_data in plan.get("days", []):
        day_number = day_data.get("day", "")
        topic = day_data.get("topic", "Study topic")
        with st.expander(f"Day {day_number}: {topic}"):
            st.markdown("**Learning objectives**")
            for objective in day_data.get("objectives", []):
                st.write("•", objective)

            st.markdown("**Estimated study time**")
            st.write(f"{day_data.get('estimated_minutes', 'Not specified')} minutes")

            st.markdown("**Activities**")
            for activity in day_data.get("activities", []):
                st.write("•", activity)

            st.markdown("**Practice task**")
            st.write(day_data.get("practice_task", "Not specified"))

            st.markdown("**Revision**")
            st.write(day_data.get("revision", "Not specified"))

            if st.button(
                "Mark topic as completed",
                key=f"complete_topic_{profile_id}_{day_number}"
            ):
                mark_topic_completed(profile_id, topic)
                st.success("Topic marked as completed.")
                st.rerun()


# =========================================================
# HOME PAGE
# =========================================================
def home_page():
    st.title("🎓 AI Personalized Learning Coach")
    st.write(
        "Your personal AI study assistant. Create a learner profile, "
        "generate a study plan, practice with quizzes, and track progress."
    )

    st.divider()
    st.header("Create a New Learner Profile")

    with st.form("profile_form"):
        name = st.text_input("Learner Name")
        subject = st.text_input("Subject to Learn")
        goal = st.text_area("What is your learning goal?")

        col1, col2 = st.columns(2)

        with col1:
            level = st.selectbox(
                "Current Learning Level",
                ["Beginner", "Intermediate", "Advanced"]
            )
            days = st.number_input(
                "Study Plan Duration (Days)",
                min_value=1,
                max_value=30,
                value=7
            )

        with col2:
            minutes = st.number_input(
                "Daily Study Time (Minutes)",
                min_value=15,
                max_value=600,
                value=60,
                step=15
            )

        submitted = st.form_submit_button(
            "Create Learner Profile",
            use_container_width=True
        )

    if submitted:
        if not name.strip() or not subject.strip() or not goal.strip():
            st.error("Please fill in all the profile details.")
        else:
            profile = {
                "name": name.strip(),
                "subject": subject.strip(),
                "goal": goal.strip(),
                "level": level,
                "days": int(days),
                "minutes": int(minutes)
            }

            try:
                profile_id = save_profile(profile)
                profile["id"] = profile_id
                st.session_state.profile_id = profile_id
                st.session_state.profile = profile
                st.session_state.current_plan = None
                clear_quiz()
                st.success(
                    f"Profile created successfully for {profile['name']}!"
                )
                st.rerun()
            except sqlite3.Error as error:
                st.error(f"Could not save profile: {error}")

    st.divider()

    if st.session_state.profile:
        profile = st.session_state.profile
        st.header("Active Learner")
        show_profile_details(profile)

        if st.button(
            "Generate My Study Plan",
            type="primary",
            use_container_width=True
        ):
            with st.spinner("Creating your personalized study plan..."):
                try:
                    plan = generate_study_plan(profile)
                    save_plan(profile["id"], plan)
                    st.session_state.current_plan = plan
                    st.success("Your study plan is ready!")
                    st.rerun()
                except Exception as error:
                    st.error(f"Could not generate study plan: {error}")

        st.divider()
        show_study_plan(profile["id"])
    else:
        st.info("Create a learner profile above or load a saved profile from the sidebar.")


# =========================================================
# QUIZ PAGE
# =========================================================
def quiz_page():
    st.title("📝 Practice Quiz")

    profile = st.session_state.profile

    if not profile:
        st.warning("Please create or load a learner profile first.")
        return

    st.write(f"Active learner: **{profile['name']}**")
    st.write(f"Subject: **{profile['subject']}**")

    topic = st.text_input(
        "Enter the topic for your quiz",
        placeholder="Example: Python basics"
    )

    if st.button("Generate Quiz", type="primary"):
        if not topic.strip():
            st.error("Please enter a topic.")
        else:
            with st.spinner("Generating your quiz..."):
                try:
                    questions = generate_quiz(
                        profile["subject"],
                        topic.strip(),
                        profile["level"]
                    )
                    st.session_state.quiz_questions = questions
                    st.session_state.quiz_topic = topic.strip()
                    st.session_state.quiz_result = None
                    st.session_state.quiz_submitted = False
                    st.rerun()
                except Exception as error:
                    st.error(f"Could not generate quiz: {error}")

    questions = st.session_state.quiz_questions

    if not questions:
        st.info("Enter a topic and click Generate Quiz to begin.")
        return

    st.divider()
    st.subheader(f"Quiz: {st.session_state.quiz_topic}")

    if st.session_state.quiz_submitted:
        result = st.session_state.quiz_result
        st.metric("Your Score", f"{result['score']} / {result['total']}")
        st.progress(result["score"] / result["total"])

        for index, question in enumerate(questions):
            st.markdown(f"**Question {index + 1}: {question['question']}**")
            st.write("Your answer:", result["answers"][index])
            st.write("Correct answer:", question["answer"])
            st.write("Explanation:", question["explanation"])
            st.divider()

        if st.button("Take Another Quiz"):
            clear_quiz()
            st.rerun()
        return

    answers = []

    for index, question in enumerate(questions):
        st.markdown(f"**{index + 1}. {question['question']}**")
        options = question["options"]
        choice = st.radio(
            f"Choose your answer for question {index + 1}",
            options=["A", "B", "C", "D"],
            format_func=lambda key, opts=options: f"{key}. {opts[key]}",
            key=f"quiz_answer_{profile['id']}_{index}",
            index=None
        )
        answers.append(choice)

    if st.button("Submit Quiz", type="primary"):
        if any(answer is None for answer in answers):
            st.warning("Please answer all five questions before submitting.")
            return

        score = sum(
            1 for answer, question in zip(answers, questions)
            if answer == question["answer"]
        )

        wrong_topics = [
            question.get("topic", st.session_state.quiz_topic)
            for answer, question in zip(answers, questions)
            if answer != question["answer"]
        ]

        try:
            save_quiz_attempt(
                profile["id"],
                profile["subject"],
                st.session_state.quiz_topic,
                score,
                len(questions),
                wrong_topics
            )
            update_topic_progress(
                profile["id"],
                st.session_state.quiz_topic,
                score,
                len(questions)
            )
            st.session_state.quiz_result = {
                "score": score,
                "total": len(questions),
                "answers": answers
            }
            st.session_state.quiz_submitted = True
            st.rerun()
        except sqlite3.Error as error:
            st.error(f"Could not save quiz result: {error}")
# =========================================================
# PROGRESS DASHBOARD
# =========================================================
def dashboard_page():
    st.title("📊 Progress Dashboard")

    profile = st.session_state.profile

    if not profile:
        st.warning("Please create or load a learner profile first.")
        return

    profile_id = profile["id"]

    st.write(f"Progress report for **{profile['name']}**")
    st.write(f"Subject: **{profile['subject']}**")

    st.divider()

    # Study progress
    progress = get_topic_progress(profile_id)

    total_topics = len(progress)
    completed_topics = sum(
        1 for item in progress if item[1] == "Completed"
    )

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric("Topics Tracked", total_topics)

    with col2:
        st.metric("Topics Completed", completed_topics)

    with col3:
        remaining = max(total_topics - completed_topics, 0)
        st.metric("Topics Remaining", remaining)

    if total_topics:
        completion_percentage = completed_topics / total_topics
        st.write("**Overall Topic Completion**")
        st.progress(completion_percentage)
        st.write(f"{completion_percentage * 100:.0f}% completed")

    st.divider()

    # Topic progress details
    st.subheader("Topic-wise Progress")

    if progress:
        for topic, status, score, total, updated_at in progress:
            with st.container(border=True):
                st.write(f"**{topic}**")
                st.write(f"Status: {status}")

                if score is not None and total:
                    percentage = score / total
                    st.progress(percentage)
                    st.write(
                        f"Latest quiz score: {score}/{total} "
                        f"({percentage * 100:.0f}%)"
                    )

                st.caption(f"Last updated: {updated_at}")
    else:
        st.info("Your topic progress will appear here after attempting quizzes.")

    st.divider()

    # Quiz history
    st.subheader("Quiz Performance History")

    history = get_quiz_attempts(profile_id)

    if history:
        scores = []

        for subject, topic, score, total, wrong_topics, created_at in history:
            scores.append((score / total) * 100 if total else 0)

            with st.expander(
                f"{topic} — {score}/{total}"
            ):
                st.write(f"**Subject:** {subject}")
                st.write(f"**Score:** {score}/{total}")

                try:
                    weak_topics = json.loads(wrong_topics)
                except (json.JSONDecodeError, TypeError):
                    weak_topics = []

                if weak_topics:
                    st.write("**Topics to revise:**")
                    for weak_topic in weak_topics:
                        st.write("•", weak_topic)
                else:
                    st.success("Excellent! No incorrect answers.")

                st.caption(created_at)

        if scores:
            average_score = sum(scores) / len(scores)
            st.metric("Average Quiz Percentage", f"{average_score:.1f}%")

    else:
        st.info("No quiz attempts are available yet.")

    st.divider()

    # Revision suggestions
    st.subheader("Revision Suggestions")

    weak_items = [
        item for item in progress
        if item[1] == "Needs revision"
    ]

    if weak_items:
        st.write("Focus on these topics:")
        for item in weak_items:
            st.write("•", item[0])
    else:
        st.success(
            "No topics currently require revision. "
            "Continue practising to maintain your progress."
        )


# =========================================================
# APPLICATION NAVIGATION
# =========================================================
def run_application():
    if page == "Home & Study Plan":
        home_page()

    elif page == "Practice Quiz":
        quiz_page()

    elif page == "Progress Dashboard":
        dashboard_page()
# =========================================================
# RUN APPLICATION
# =========================================================
if __name__ == "__main__":
    run_application()      
          
          
          
