import os
import json
import sqlite3
from datetime import datetime

import streamlit as st
from dotenv import load_dotenv
from openai import OpenAI


# =========================================================
# 1. CONFIGURATION
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


def get_ai_client():
    api_key = get_secret("GROQ_API_KEY")

    if not api_key:
        raise ValueError(
            "GROQ_API_KEY is missing. Add it in Streamlit Secrets."
        )

    return OpenAI(
        api_key=api_key,
        base_url="https://api.groq.com/openai/v1"
    )


def ask_ai(prompt):
    client = get_ai_client()

    model = get_secret("GROQ_MODEL", DEFAULT_MODEL)

    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are an educational AI learning coach. "
                    "Create clear, accurate, beginner-friendly "
                    "learning content. Return valid JSON when requested."
                )
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        temperature=0.3
    )

    result = response.choices[0].message.content

    if not result:
        raise ValueError("The AI returned an empty response.")

    return result.strip()


def extract_json(text):
    text = text.strip()

    if text.startswith("```"):
        lines = text.splitlines()

        if lines and lines[0].startswith("```"):
            lines = lines[1:]

        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]

        text = "\n".join(lines).strip()

    start = text.find("{")
    end = text.rfind("}")

    if start == -1 or end == -1:
        raise ValueError("Invalid JSON response from AI.")

    return json.loads(text[start:end + 1])


# =========================================================
# 2. DATABASE
# =========================================================

def get_connection():
    connection = sqlite3.connect(DB_NAME, timeout=20)
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


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
    with get_connection() as conn:
        cursor = conn.execute("""
            INSERT INTO profiles
            (name, subject, goal, level, days, daily_minutes, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            profile["name"],
            profile["subject"],
            profile["goal"],
            profile["level"],
            profile["days"],
            profile["minutes"],
            datetime.now().isoformat(timespec="seconds")
        ))

        return cursor.lastrowid


def update_profile(profile_id, profile):
    with get_connection() as conn:
        conn.execute("""
            UPDATE profiles
            SET name=?, subject=?, goal=?, level=?, days=?, daily_minutes=?
            WHERE id=?
        """, (
            profile["name"],
            profile["subject"],
            profile["goal"],
            profile["level"],
            profile["days"],
            profile["minutes"],
            profile_id
        ))


def get_profiles():
    with get_connection() as conn:
        return conn.execute("""
            SELECT id, name, subject, goal, level, days, daily_minutes
            FROM profiles
            ORDER BY id DESC
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
            SELECT plan_json
            FROM plans
            WHERE profile_id=?
            ORDER BY id DESC
            LIMIT 1
        """, (profile_id,)).fetchone()

    if row:
        try:
            return json.loads(row[0])
        except (json.JSONDecodeError, TypeError):
            return None

    return None


def save_quiz_attempt(profile_id, subject, topic, score, total, wrong_topics):
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO quiz_attempts
            (profile_id, subject, topic, score, total, wrong_topics, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            profile_id,
            subject,
            topic,
            score,
            total,
            json.dumps(wrong_topics),
            datetime.now().isoformat(timespec="seconds")
        ))


def update_topic_progress(profile_id, topic, score, total):
    percentage = (score / total) * 100 if total else 0

    if percentage < 60:
        status = "Needs revision"
    else:
        status = "In progress"

    with get_connection() as conn:
        conn.execute("""
            INSERT INTO topic_progress
            (profile_id, topic, status, score, total, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(profile_id, topic)
            DO UPDATE SET
                status=excluded.status,
                score=excluded.score,
                total=excluded.total,
                updated_at=excluded.updated_at
        """, (
            profile_id,
            topic,
            status,
            score,
            total,
            datetime.now().isoformat(timespec="seconds")
        ))


def mark_topic_completed(profile_id, topic):
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO topic_progress
            (profile_id, topic, status, updated_at)
            VALUES (?, ?, 'Completed', ?)
            ON CONFLICT(profile_id, topic)
            DO UPDATE SET
                status='Completed',
                updated_at=excluded.updated_at
        """, (
            profile_id,
            topic,
            datetime.now().isoformat(timespec="seconds")
        ))


def get_topic_progress(profile_id):
    with get_connection() as conn:
        return conn.execute("""
            SELECT topic, status, score, total, updated_at
            FROM topic_progress
            WHERE profile_id=?
            ORDER BY topic
        """, (profile_id,)).fetchall()


def get_quiz_attempts(profile_id):
    with get_connection() as conn:
        return conn.execute("""
            SELECT subject, topic, score, total, wrong_topics, created_at
            FROM quiz_attempts
            WHERE profile_id=?
            ORDER BY id DESC
        """, (profile_id,)).fetchall()


# =========================================================
# 3. STUDY PLAN GENERATION
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
  "overview": "Short description of the learning plan",
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
1. Return exactly {profile['days']} days.
2. Estimated minutes must not exceed {profile['minutes']}.
3. Include learning objectives.
4. Include activities and a practice task.
5. Arrange topics in a logical learning order.
6. Use simple language.
7. Return JSON only.
"""

    data = extract_json(ask_ai(prompt))

    if not isinstance(data, dict):
        raise ValueError("Invalid study plan format.")

    days = data.get("days")

    if not isinstance(days, list) or len(days) != profile["days"]:
        raise ValueError("The AI did not return the requested number of days.")

    for index, day in enumerate(days, start=1):

        required = [
            "topic",
            "objectives",
            "activities",
            "practice_task",
            "revision",
            "estimated_minutes"
        ]

        for field in required:
            if field not in day:
                raise ValueError(f"Day {index} is missing {field}.")

        if not isinstance(day["topic"], str) or not day["topic"].strip():
            raise ValueError(f"Day {index} has an invalid topic.")

        if not isinstance(day["objectives"], list):
            raise ValueError(f"Day {index} has invalid objectives.")

        if not isinstance(day["activities"], list):
            raise ValueError(f"Day {index} has invalid activities.")

        minutes = int(day["estimated_minutes"])

        if minutes <= 0 or minutes > profile["minutes"]:
            raise ValueError(f"Day {index} has an invalid time estimate.")

        day["day"] = index
        day["estimated_minutes"] = minutes

    data.setdefault("overview", "Your personalized learning journey.")

    return data


# =========================================================
# 4. QUIZ GENERATION
# =========================================================

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
      "options": {{
        "A": "Option A",
        "B": "Option B",
        "C": "Option C",
        "D": "Option D"
      }},
      "answer": "A",
      "explanation": "Explanation of the correct answer",
      "topic": "Concept tested"
    }}
  ]
}}

Rules:
- Exactly 5 questions.
- Four options for every question.
- Only one correct answer.
- Answer must be A, B, C, or D.
- Include explanations.
- Keep questions related to the given topic.
- Return JSON only.
"""

    data = extract_json(ask_ai(prompt))

    questions = data.get("questions")

    if not isinstance(questions, list) or len(questions) != 5:
        raise ValueError("The AI did not generate five questions.")

    for index, question in enumerate(questions, start=1):

        options = question.get("options")

        if not isinstance(options, dict):
            raise ValueError(f"Question {index} has invalid options.")

        for key in ["A", "B", "C", "D"]:
            if not isinstance(options.get(key), str) or not options[key].strip():
                raise ValueError(f"Question {index} is missing option {key}.")

        if question.get("answer") not in ["A", "B", "C", "D"]:
            raise ValueError(f"Question {index} has an invalid answer.")

        if not question.get("question"):
            raise ValueError(f"Question {index} is empty.")

        question.setdefault("explanation", "Review this concept.")
        question.setdefault("topic", topic)

    return questions


# =========================================================
# 5. SESSION STATE
# =========================================================

def clear_quiz():
    st.session_state.quiz_questions = None
    st.session_state.quiz_result = None
    st.session_state.quiz_submitted = False
    st.session_state.quiz_topic = ""


def load_profile(row):
    st.session_state.profile_id = row[0]

    st.session_state.profile = {
        "name": row[1],
        "subject": row[2],
        "goal": row[3],
        "level": row[4],
        "days": row[5],
        "minutes": row[6]
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


# =========================================================
# 6. INITIALIZE APPLICATION
# =========================================================

try:
    initialize_database()
except sqlite3.Error as error:
    st.error(f"Database initialization failed: {error}")
    st.stop()


# =========================================================
# 7. SIDEBAR NAVIGATION
# =========================================================

st.sidebar.title("🎓 Learning Coach")
st.sidebar.write("Your AI-powered study companion")

page = st.sidebar.radio(
    "Choose a page",
    [
        "Home & Study Plan",
        "Practice Quiz",
        "Progress Dashboard"
    ]
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
        "Saved Learner Profiles",
        list(profile_labels.keys())
    )

    if st.sidebar.button("Load Profile"):

        selected_row = profile_labels[selected_label]

        load_profile(selected_row)

        st.sidebar.success("Profile loaded successfully.")

if st.session_state.profile:
    st.sidebar.success(
        f"Active learner: {st.session_state.profile['name']}"
    )
else:
    st.sidebar.info("Create a learner profile to begin.")


# =========================================================
# 8. HOME AND STUDY PLAN PAGE
# =========================================================

if page == "Home & Study Plan":

    st.title("🎓 AI Personalized Learning Coach")

    st.write(
        "Create your own personalized study plan, practise quizzes, "
        "receive feedback, and track your learning progress."
    )

    st.divider()

    st.subheader("Create Your Learning Profile")

    active = st.session_state.profile or {}

    with st.form("profile_form"):

        name = st.text_input(
            "Learner Name",
            value=active.get("name", "")
        )

        subject = st.text_input(
            "Subject",
            value=active.get("subject", "")
        )

        goal = st.text_area(
            "What is your learning goal?",
            value=active.get("goal", "")
        )

        levels = ["Beginner", "Intermediate", "Advanced"]

        current_level = active.get("level", "Beginner")

        level = st.selectbox(
            "Current Skill Level",
            levels,
            index=levels.index(current_level)
            if current_level in levels else 0
        )

        col1, col2 = st.columns(2)

        with col1:
            days = st.number_input(
                "Target Duration (Days)",
                min_value=1,
                max_value=90,
                value=int(active.get("days", 7))
            )

        with col2:
            minutes = st.number_input(
                "Daily Study Time (Minutes)",
                min_value=10,
                max_value=480,
                value=int(active.get("minutes", 60)),
                step=5
            )

        generate_button = st.form_submit_button(
            "Generate My Study Plan",
            type="primary"
        )

    if generate_button:

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

            with st.spinner("Generating your personalized study plan..."):

                try:

                    plan = generate_study_plan(profile)

                    if st.session_state.profile_id:

                        profile_id = st.session_state.profile_id

                        update_profile(profile_id, profile)

                    else:

                        profile_id = save_profile(profile)

                    save_plan(profile_id, plan)

                    st.session_state.profile_id = profile_id
                    st.session_state.profile = profile
                    st.session_state.current_plan = plan

                    clear_quiz()

                    st.success("Your study plan has been generated and saved!")

                except Exception as error:

                    st.error(f"Could not generate your study plan: {error}")

    # Display the saved study plan

    if st.session_state.profile and st.session_state.current_plan:

        profile = st.session_state.profile
        plan = st.session_state.current_plan

        st.divider()

        st.subheader("Your Personalized Study Plan")

        st.write(f"**Learner:** {profile['name']}")
        st.write(f"**Subject:** {profile['subject']}")
        st.write(f"**Goal:** {profile['goal']}")
        st.write(f"**Level:** {profile['level']}")

        st.info(plan.get("overview", "Your learning journey begins here."))

        try:
            progress_rows = get_topic_progress(st.session_state.profile_id)
            progress_map = {
                row[0]: row[1]
                for row in progress_rows
            }
        except sqlite3.Error:
            progress_map = {}

        for day in plan["days"]:

            topic = day["topic"]
            status = progress_map.get(topic, "Pending")

            with st.expander(
                f"Day {day['day']}: {topic} - {status}"
            ):

                st.write(
                    f"**Estimated Time:** {day['estimated_minutes']} minutes"
                )

                st.markdown("**Learning Objectives**")

                for objective in day["objectives"]:
                    st.write(f"- {objective}")

                st.markdown("**Learning Activities**")

                for activity in day["activities"]:
                    st.write(f"- {activity}")

                st.markdown("**Practice Task**")
                st.write(day["practice_task"])

                st.markdown("**Revision Activity**")
                st.write(day["revision"])

                if status != "Completed":

                    if st.button(
                        "Mark as Completed",
                        key=f"complete_{day['day']}_{st.session_state.profile_id}"
                    ):

                        try:
                            mark_topic_completed(
                                st.session_state.profile_id,
                                topic
                            )

                            st.success("Topic marked as completed.")

                            st.rerun()

                        except sqlite3.Error as error:
                            st.error(f"Could not update progress: {error}")

        st.download_button(
            "Download Study Plan",
            data=json.dumps(plan, indent=2, ensure_ascii=False),
            file_name="study_plan.json",
            mime="application/json"
        )

    elif st.session_state.profile:

        st.info("Generate a study plan using the form above.")


# =========================================================
# 9. PRACTICE QUIZ PAGE
# =========================================================

elif page == "Practice Quiz":

    st.title("📝 Practice Quiz")

    st.write(
        "Test your knowledge with five AI-generated questions."
    )

    if not st.session_state.profile:

        st.warning("Please create or load a learner profile first.")

    else:

        profile = st.session_state.profile

        st.write(f"**Subject:** {profile['subject']}")
        st.write(f"**Level:** {profile['level']}")

        plan = st.session_state.current_plan

        topics = []

        if plan:

            topics = [
                day["topic"]
                for day in plan.get("days", [])
            ]

        if topics:

            selected_topic = st.selectbox(
                "Choose a topic",
                ["Select a topic"] + topics
            )

        else:

            selected_topic = "Select a topic"

        custom_topic = st.text_input(
            "Or enter another topic",
            placeholder="Example: Python Functions"
        )

        if custom_topic.strip():

            topic = custom_topic.strip()

        elif selected_topic != "Select a topic":

            topic = selected_topic

        else:

            topic = ""

        if st.button("Generate 5 Questions", type="primary"):

            if not topic:

                st.warning("Please select or enter a topic.")

            else:

                with st.spinner("Generating your quiz..."):

                    try:

                        questions = generate_quiz(
                            profile["subject"],
                            topic,
                            profile["level"]
                        )

                        st.session_state.quiz_questions = questions
                        st.session_state.quiz_topic = topic
                        st.session_state.quiz_result = None
                        st.session_state.quiz_submitted = False

                        st.rerun()

                    except Exception as error:

                        st.error(f"Quiz generation failed: {error}")

        questions = st.session_state.quiz_questions

        if questions:

            st.divider()

            st.subheader(
                f"Quiz: {st.session_state.quiz_topic}"
            )

            if not st.session_state.quiz_submitted:

                with st.form("quiz_form"):

                    answers = []

                    for index, question in enumerate(questions):

                        st.markdown(
                            f"**Question {index + 1}: "
                            f"{question['question']}**"
                        )

                        options = question["options"]

                        answer = st.radio(
                            f"Select your answer for Question {index + 1}",
                            ["A", "B", "C", "D"],
                            format_func=lambda key, opts=options: (
                                f"{key}. {opts[key]}"
                            ),
                            key=f"question_{index}"
                        )

                        answers.append(answer)

                    submit_quiz = st.form_submit_button(
                        "Submit Quiz",
                        type="primary"
                    )

                if submit_quiz:

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
                            wrong_topics.append(
                                question.get(
                                    "topic",
                                    st.session_state.quiz_topic
                                )
                            )

                        results.append({
                            "question": question["question"],
                            "selected": selected,
                            "correct": correct,
                            "options": question["options"],
                            "is_correct": is_correct,
                            "explanation": question["explanation"],
                            "topic": question.get(
                                "topic",
                                st.session_state.quiz_topic
                            )
                        })

                    try:

                        save_quiz_attempt(
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

                        st.error(f"Could not save quiz results: {error}")
                        st.stop()

                    st.session_state.quiz_result = {
                        "score": score,
                        "total": len(questions),
                        "results": results,
                        "wrong_topics": wrong_topics
                    }

                    st.session_state.quiz_submitted = True

                    st.rerun()

            # Display quiz results

            if st.session_state.quiz_submitted:

                result = st.session_state.quiz_result

                score = result["score"]
                total = result["total"]

                percentage = round((score / total) * 100)

                st.subheader("Your Quiz Results")

                col1, col2 = st.columns(2)

                col1.metric("Your Score", f"{score}/{total}")
                col2.metric("Accuracy", f"{percentage}%")

                st.progress(percentage / 100)

                if percentage >= 80:

                    st.success(
                        "Good performance! Continue practising "
                        "and try the next topic."
                    )

                elif percentage >= 60:

                    st.info(
                        "Good effort! Review the explanations "
                        "and practise again."
                    )

                else:

                    st.warning(
                        "This topic needs more revision. "
                        "Review the concepts before trying again."
                    )

                st.divider()

                st.subheader("Answer Explanations")

                for index, item in enumerate(result["results"]):

                    with st.expander(
                        f"Question {index + 1}"
                    ):

                        st.write(item["question"])

                        st.write(
                            f"**Your Answer:** {item['selected']}. "
                            f"{item['options'][item['selected']]}"
                        )

                        st.write(
                            f"**Correct Answer:** {item['correct']}. "
                            f"{item['options'][item['correct']]}"
                        )

                        st.write(
                            f"**Explanation:** {item['explanation']}"
                        )

                        st.write(
                            f"**Concept:** {item['topic']}"
                        )

                        if item["is_correct"]:
                            st.success("Correct answer!")
                        else:
                            st.error("Review this concept.")

                st.divider()

                st.subheader("Personalized Recommendations")

                if result["wrong_topics"]:

                    st.write("Topics recommended for revision:")

                    for weak_topic in sorted(
                        set(result["wrong_topics"])
                    ):
                        st.write(f"- {weak_topic}")

                    st.info(
                        "Revise these topics and take another quiz."
                    )

                else:

                    st.success(
                        "You answered all five questions correctly "
                        "in this attempt."
                    )

                    if plan:

                        plan_topics = [
                            day["topic"]
                            for day in plan.get("days", [])
                        ]

                        current_index = next(
                            (
                                index
                                for index, value in enumerate(plan_topics)
                                if value.lower() ==
                                st.session_state.quiz_topic.lower()
                            ),
                            None
                        )

                        if (
                            current_index is not None
                            and current_index + 1 < len(plan_topics)
                        ):

                            st.write(
                                "**Suggested Next Topic:** "
                                f"{plan_topics[current_index + 1]}"
                            )

                if st.button("Try Another Quiz"):

                    clear_quiz()

                    st.rerun()


# =========================================================
# 10. PROGRESS DASHBOARD
# =========================================================

elif page == "Progress Dashboard":

    st.title("📊 Learning Progress Dashboard")

    st.write(
        "View your study progress, quiz performance, "
        "completed topics, and revision recommendations."
    )

    try:
        profiles = get_profiles()
    except sqlite3.Error as error:
        st.error(f"Could not load profiles: {error}")
        profiles = []

    if not profiles:

        st.info("Create a learner profile to view your dashboard.")

    else:

        profile_options = {
            f"{row[1]} - {row[2]} (ID: {row[0]})": row
            for row in profiles
        }

        selected_label = st.selectbox(
            "Select Learner",
            list(profile_options.keys())
        )

        selected_profile = profile_options[selected_label]
        selected_id = selected_profile[0]

        col1, col2, col3 = st.columns(3)

        col1.metric("Target Days", selected_profile[5])

        col2.metric(
            "Daily Study Time",
            f"{selected_profile[6]} minutes"
        )

        col3.metric("Skill Level", selected_profile[4])

        st.write(f"**Learning Goal:** {selected_profile[3]}")

        try:

            plan = get_latest_plan(selected_id)
            progress = get_topic_progress(selected_id)
            attempts = get_quiz_attempts(selected_id)

        except sqlite3.Error as error:

            st.error(f"Could not load dashboard information: {error}")

            plan = None
            progress = []
            attempts = []

        # Topic progress

        st.divider()

        st.subheader("Topic Completion")

        if plan:

            progress_map = {
                row[0]: row[1]
                for row in progress
            }

            completed = 0
            topic_data = []

            for day in plan.get("days", []):

                topic_name = day["topic"]

                status = progress_map.get(
                    topic_name,
                    "Pending"
                )

                if status == "Completed":
                    completed += 1

                topic_data.append({
                    "Day": day["day"],
                    "Topic": topic_name,
                    "Status": status
                })

            st.dataframe(
                topic_data,
                use_container_width=True,
                hide_index=True
            )

            total_topics = len(topic_data)
            pending = total_topics - completed

            col1, col2 = st.columns(2)

            col1.metric("Completed Topics", completed)
            col2.metric("Remaining Topics", pending)

            if total_topics:

                completion_percentage = (
                    completed / total_topics
                )

                st.progress(completion_percentage)

                st.write(
                    f"Overall topic completion: "
                    f"{round(completion_percentage * 100)}%"
                )

            next_topic = next(
                (
                    item["Topic"]
                    for item in topic_data
                    if item["Status"] != "Completed"
                ),
                None
            )

            if next_topic:

                st.info(
                    f"**Next Study Action:** Continue with {next_topic}"
                )

            else:

                st.success("All topics in this plan are completed.")

        else:

            st.info("Generate a study plan to see topic progress.")

        # Quiz performance

        st.divider()

        st.subheader("Quiz Performance")

        if attempts:

            total_quizzes = len(attempts)

            total_questions = sum(
                row[3]
                for row in attempts
            )

            total_correct = sum(
                row[2]
                for row in attempts
            )

            accuracy = (
                round((total_correct / total_questions) * 100)
                if total_questions else 0
            )

            col1, col2, col3 = st.columns(3)

            col1.metric("Quizzes Completed", total_quizzes)

            col2.metric(
                "Questions Answered",
                total_questions
            )

            col3.metric(
                "Overall Accuracy",
                f"{accuracy}%"
            )

            st.progress(accuracy / 100)

            st.subheader("Recent Quiz Attempts")

            for attempt in attempts[:10]:

                subject_name = attempt[0]
                topic_name = attempt[1]
                score = attempt[2]
                total = attempt[3]
                wrong_json = attempt[4]
                created_at = attempt[5]

                with st.expander(
                    f"{topic_name} - {score}/{total}"
                ):

                    st.write(f"**Subject:** {subject_name}")

                    st.write(f"**Date:** {created_at}")

                    try:
                        weak_topics = json.loads(wrong_json)
                    except (json.JSONDecodeError, TypeError):
                        weak_topics = []

                    if weak_topics:

                        st.write("**Topics to revise:**")

                        for weak in sorted(set(weak_topics)):
                            st.write(f"- {weak}")

                    else:

                        st.write("No incorrect answers in this attempt.")

            chart_data = []

            for index, attempt in enumerate(reversed(attempts)):

                score = attempt[2]
                total = attempt[3]

                percentage = (
                    round((score / total) * 100)
                    if total else 0
                )

                chart_data.append({
                    "Attempt": f"Quiz {index + 1}",
                    "Accuracy": percentage
                })

            st.subheader("Quiz Accuracy History")

            st.line_chart(
                chart_data,
                x="Attempt",
                y="Accuracy"
            )

        else:

            st.info("Complete a quiz to see your performance history.")

        # Revision recommendations

        st.divider()

        st.subheader("Topics Needing Revision")

        revision_topics = [
            row[0]
            for row in progress
            if row[1] == "Needs revision"
        ]

        if revision_topics:

            for topic in revision_topics:
                st.write(f"- {topic}")

        else:

            st.write("No topics are currently flagged for revision.")


# =========================================================
# 11. FOOTER
# =========================================================

st.divider()

st.caption(
    "AI Personalized Learning Coach | "
    "Python | Streamlit | Groq API | SQLite"
)

st.caption(
    "AI-generated educational content may contain errors. "
    "Use explanations and revision activities to support your learning."
)
