
import os
import json
import sqlite3
from datetime import datetime

import streamlit as st
from dotenv import load_dotenv
from openai import OpenAI

# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

load_dotenv()

st.set_page_config(
    page_title="AI Personalized Learning Coach",
    page_icon="🎓",
    layout="wide"
)

DB_NAME = "learning_coach.db"


def get_config(name, default=None):
    """Read configuration from environment variables or Streamlit Secrets."""
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
            "Groq API key is missing. Add GROQ_API_KEY to your local .env "
            "file or Streamlit Cloud Secrets."
        )

    return OpenAI(
        api_key=api_key,
        base_url="https://api.groq.com/openai/v1"
    )


def ask_ai(prompt):
    client = get_ai_client()
    model = get_config("GROQ_MODEL", "openai/gpt-oss-120b")

    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a helpful AI Personalized Learning Coach. "
                    "Give accurate, beginner-friendly educational content. "
                    "When JSON is requested, return valid JSON only."
                )
            },
            {"role": "user", "content": prompt}
        ],
        temperature=0.4
    )

    content = response.choices[0].message.content

    if not content:
        raise ValueError("The AI returned an empty response.")

    return content.strip()


def extract_json(text):
    """Extract JSON if the AI wraps its response in Markdown."""
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
        raise ValueError("The AI response did not contain valid JSON.")

    return json.loads(text[start:end + 1])


# --------------------------------------------------
# DATABASE
# --------------------------------------------------

def get_connection():
    return sqlite3.connect(DB_NAME)


def initialize_database():
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


initialize_database()


# --------------------------------------------------
# DATABASE FUNCTIONS
# --------------------------------------------------

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


def save_plan(profile_id, plan):
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO learning_plans
            (profile_id, plan_json, created_at)
            VALUES (?, ?, ?)
        """, (
            profile_id,
            json.dumps(plan),
            datetime.now().isoformat(timespec="seconds")
        ))


def save_attempt(profile_id, subject, topic, score, total, wrong_topics):
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO quiz_attempts
            (profile_id, subject, topic, score, total_questions,
             wrong_topics, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            profile_id, subject, topic, score, total,
            json.dumps(wrong_topics),
            datetime.now().isoformat(timespec="seconds")
        ))


def load_profiles():
    with get_connection() as conn:
        return conn.execute("""
            SELECT id, learner_name, subject, learning_goal,
                   skill_level, target_days, daily_minutes, created_at
            FROM learner_profiles
            ORDER BY id DESC
        """).fetchall()


def load_plans(profile_id):
    with get_connection() as conn:
        return conn.execute("""
            SELECT id, plan_json, created_at
            FROM learning_plans
            WHERE profile_id = ?
            ORDER BY id DESC
        """, (profile_id,)).fetchall()


def load_attempts(profile_id):
    with get_connection() as conn:
        return conn.execute("""
            SELECT subject, topic, score, total_questions,
                   wrong_topics, created_at
            FROM quiz_attempts
            WHERE profile_id = ?
            ORDER BY id DESC
        """, (profile_id,)).fetchall()


# --------------------------------------------------
# AI STUDY PLAN
# --------------------------------------------------

def generate_study_plan(profile):
    prompt = f"""
Create a personalized learning plan as valid JSON.

Learner name: {profile['name']}
Subject: {profile['subject']}
Learning goal: {profile['goal']}
Current level: {profile['level']}
Number of days: {profile['days']}
Daily study time: {profile['minutes']} minutes

Return this JSON structure:
{{
  "overview": "Short description of the plan",
  "days": [
    {{
      "day": 1,
      "topic": "Topic name",
      "objectives": ["Objective 1", "Objective 2"],
      "activities": ["Activity 1", "Activity 2"],
      "practice_task": "A task the learner should complete",
      "revision": "A short revision activity"
    }}
  ]
}}

Requirements:
- Create exactly {profile['days']} day entries.
- Progress from basic to more advanced concepts.
- Keep the workload realistic for the daily time available.
- Use clear, beginner-friendly language.
- Make the plan relevant to the stated goal.
- Return valid JSON only.
"""

    data = extract_json(ask_ai(prompt))

    if not isinstance(data.get("days"), list) or not data["days"]:
        raise ValueError("The AI did not return a usable day-wise plan.")

    return data


# --------------------------------------------------
# AI QUIZ
# --------------------------------------------------

def generate_quiz(subject, topic, level):
    prompt = f"""
Create exactly 5 multiple-choice questions.

Subject: {subject}
Topic: {topic}
Learner level: {level}

Return valid JSON only in this format:
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
      "explanation": "Explain why the correct answer is right",
      "topic": "Specific concept being tested"
    }}
  ]
}}

Rules:
- Each answer must be exactly A, B, C, or D.
- Include four different options per question.
- Only one option should be correct.
- Keep questions relevant to the subject and topic.
- Use clear language suitable for the learner's level.
- Return exactly 5 questions.
- Return valid JSON only.
"""

    data = extract_json(ask_ai(prompt))
    questions = data.get("questions", [])

    if len(questions) != 5:
        raise ValueError("The AI did not generate exactly 5 questions.")

    for question in questions:
        if (
            not isinstance(question.get("options"), dict)
            or not all(k in question["options"] for k in ["A", "B", "C", "D"])
            or question.get("answer") not in ["A", "B", "C", "D"]
        ):
            raise ValueError("The AI returned an incorrectly formatted quiz.")

    return questions


# --------------------------------------------------
# SESSION STATE
# --------------------------------------------------

if "profile_id" not in st.session_state:
    st.session_state.profile_id = None

if "profile" not in st.session_state:
    st.session_state.profile = None

if "current_plan" not in st.session_state:
    st.session_state.current_plan = None

if "quiz_questions" not in st.session_state:
    st.session_state.quiz_questions = None

if "quiz_topic" not in st.session_state:
    st.session_state.quiz_topic = ""

if "quiz_submitted" not in st.session_state:
    st.session_state.quiz_submitted = False

if "quiz_result" not in st.session_state:
    st.session_state.quiz_result = None


# --------------------------------------------------
# SIDEBAR
# --------------------------------------------------

st.sidebar.title("🎓 Learning Coach")
st.sidebar.caption("Your personal AI-powered study companion")

page = st.sidebar.radio(
    "Navigate",
    [
        "🏠 Home & Study Plan",
        "📝 Practice Quiz",
        "📊 Progress Dashboard"
    ]
)

st.sidebar.divider()

if st.session_state.profile:
    st.sidebar.success(
        f"Active learner: {st.session_state.profile['name']}"
    )
else:
    st.sidebar.info("Create a learner profile to get started.")


# --------------------------------------------------
# HOME AND STUDY PLAN
# --------------------------------------------------

if page == "🏠 Home & Study Plan":
    st.title("🎓 AI Personalized Learning Coach")
    st.write(
        "Create a personalized study plan, practise quizzes, "
        "understand your mistakes, and track your learning progress."
    )

    st.subheader("1. Set up your learning profile")

    with st.form("profile_form"):
        name = st.text_input("Learner name", placeholder="Enter your name")

        subject = st.text_input(
            "Subject",
            placeholder="Example: Python, Mathematics, DBMS"
        )

        goal = st.text_area(
            "Learning goal",
            placeholder="Example: Learn Python fundamentals and solve problems"
        )

        level = st.selectbox(
            "Current skill level",
            ["Beginner", "Intermediate", "Advanced"]
        )

        col1, col2 = st.columns(2)

        with col1:
            days = st.number_input(
                "Target duration (days)",
                min_value=1,
                max_value=90,
                value=7
            )

        with col2:
            minutes = st.number_input(
                "Daily study time (minutes)",
                min_value=10,
                max_value=480,
                value=60,
                step=10
            )

        submitted = st.form_submit_button(
            "Create My Study Plan",
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

                    profile_id = save_profile(
                        profile["name"],
                        profile["subject"],
                        profile["goal"],
                        profile["level"],
                        profile["days"],
                        profile["minutes"]
                    )

                    save_plan(profile_id, plan)

                    st.session_state.profile = profile
                    st.session_state.profile_id = profile_id
                    st.session_state.current_plan = plan
                    st.session_state.quiz_questions = None
                    st.session_state.quiz_submitted = False
                    st.session_state.quiz_result = None

                    st.success("Your personalized study plan is ready!")

                except Exception as error:
                    st.error(f"Could not generate the study plan: {error}")
                    st.info(
                        "Check your API key, internet connection, and model "
                        "availability, then try again."
                    )

    if st.session_state.current_plan:
        profile = st.session_state.profile
        plan = st.session_state.current_plan

        st.divider()
        st.subheader("2. Your personalized learning plan")

        st.write(f"**Learner:** {profile['name']}")
        st.write(f"**Subject:** {profile['subject']}")
        st.write(f"**Goal:** {profile['goal']}")
        st.write(f"**Level:** {profile['level']}")
        st.info(plan.get("overview", "Your learning journey starts here."))

        for day_item in plan.get("days", []):
            day_number = day_item.get("day", "?")
            topic = day_item.get("topic", "Study topic")

            with st.expander(f"Day {day_number}: {topic}"):
                st.markdown("**Learning objectives**")
                for objective in day_item.get("objectives", []):
                    st.write(f"- {objective}")

                st.markdown("**Activities**")
                for activity in day_item.get("activities", []):
                    st.write(f"- {activity}")

                st.markdown("**Practice task**")
                st.write(day_item.get("practice_task", "Review the topic."))

                st.markdown("**Revision**")
                st.write(day_item.get("revision", "Revise today's concepts."))

        st.download_button(
            "Download Study Plan (JSON)",
            data=json.dumps(plan, indent=2),
            file_name="personalized_study_plan.json",
            mime="application/json"
        )

        if st.button("Start a Practice Quiz", type="primary"):
            st.session_state["navigate_to_quiz"] = True
            st.rerun()


# --------------------------------------------------
# PRACTICE QUIZ
# --------------------------------------------------

elif page == "📝 Practice Quiz":
    st.title("📝 Topic-Based Practice Quiz")
    st.write(
        "Answer five multiple-choice questions. Your score is calculated "
        "in Python using the answer key, and you will receive explanations."
    )

    if not st.session_state.profile:
        st.warning(
            "Please create a learner profile and study plan on the Home page first."
        )
    else:
        profile = st.session_state.profile

        st.write(f"**Subject:** {profile['subject']}")
        st.write(f"**Level:** {profile['level']}")

        topic = st.text_input(
            "Topic to practise",
            value=st.session_state.quiz_topic,
            placeholder="Example: Python loops"
        )

        if st.button("Generate 5 Questions", type="primary"):
            if not topic.strip():
                st.warning("Enter a topic first.")
            else:
                with st.spinner("Preparing your quiz..."):
                    try:
                        questions = generate_quiz(
                            profile["subject"],
                            topic.strip(),
                            profile["level"]
                        )

                        st.session_state.quiz_questions = questions
                        st.session_state.quiz_topic = topic.strip()
                        st.session_state.quiz_submitted = False
                        st.session_state.quiz_result = None
                        st.rerun()

                    except Exception as error:
                        st.error(f"Could not generate the quiz: {error}")

        questions = st.session_state.quiz_questions

        if questions:
            st.divider()
            st.subheader(f"Quiz: {st.session_state.quiz_topic}")

            if not st.session_state.quiz_submitted:
                with st.form("quiz_form"):
                    answers = []

                    for index, question in enumerate(questions):
                        st.markdown(
                            f"**Question {index + 1}: "
                            f"{question['question']}**"
                        )

                        options = question["options"]

                        choice = st.radio(
                            f"Choose your answer for Question {index + 1}",
                            options=["A", "B", "C", "D"],
                            format_func=lambda key, opts=options: (
                                f"{key}. {opts[key]}"
                            ),
                            key=f"answer_{index}"
                        )

                        answers.append(choice)
                        st.write("")

                    quiz_submit = st.form_submit_button(
                        "Submit Quiz",
                        type="primary"
                    )

                if quiz_submit:
                    score = 0
                    wrong_topics = []
                    results = []

                    # Score is calculated locally in Python.
                    for index, question in enumerate(questions):
                        selected = answers[index]
                        correct = question["answer"]
                        is_correct = selected == correct

                        if is_correct:
                            score += 1
                        else:
                            wrong_topics.append(
                                question.get("topic", st.session_state.quiz_topic)
                            )

                        results.append({
                            "question": question["question"],
                            "selected": selected,
                            "correct": correct,
                            "options": question["options"],
                            "is_correct": is_correct,
                            "explanation": question.get(
                                "explanation",
                                "Review the correct answer and practise again."
                            ),
                            "topic": question.get(
                                "topic", st.session_state.quiz_topic
                            )
                        })

                    save_attempt(
                        st.session_state.profile_id,
                        profile["subject"],
                        st.session_state.quiz_topic,
                        score,
                        len(questions),
                        wrong_topics
                    )

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
                    st.success("Excellent work! Keep practising to retain your knowledge.")
                elif percentage >= 50:
                    st.info("Good effort! Review the explanations and practise again.")
                else:
                    st.warning("Spend more time reviewing this topic before retrying.")

                st.subheader("Answer Review")

                for index, item in enumerate(result["results"]):
                    with st.expander(
                        f"Question {index + 1}: "
                        f"{'Correct' if item['is_correct'] else 'Needs review'}"
                    ):
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

                st.subheader("Personalized Recommendations")

                if result["wrong_topics"]:
                    weak_topics = sorted(set(result["wrong_topics"]))
                    st.write("Review these concepts:")
                    for weak_topic in weak_topics:
                        st.write(f"- {weak_topic}")
                    st.write(
                        "Revisit these concepts in your study plan and take "
                        "another quiz after revision."
                    )
                else:
                    st.success(
                        "You answered every question correctly. Try a more "
                        "advanced topic to challenge yourself."
                    )

                if st.button("Try Another Quiz"):
                    st.session_state.quiz_questions = None
                    st.session_state.quiz_submitted = False
                    st.session_state.quiz_result = None
                    st.rerun()


# --------------------------------------------------
# PROGRESS DASHBOARD
# --------------------------------------------------

elif page == "📊 Progress Dashboard":
    st.title("📊 Learning Progress Dashboard")
    st.write("Review your saved learning plans and quiz performance.")

    profiles = load_profiles()

    if not profiles:
        st.info(
            "No learner profiles found yet. Create your first study plan "
            "on the Home page."
        )
    else:
        profile_options = {
            f"{row[1]} — {row[2]} (Profile {row[0]})": row[0]
            for row in profiles
        }

        selected_label = st.selectbox(
            "Choose a learner profile",
            list(profile_options.keys())
        )

        selected_id = profile_options[selected_label]

        selected_profile = next(
            row for row in profiles if row[0] == selected_id
        )

        st.subheader("Learner Information")
        col1, col2, col3 = st.columns(3)

        col1.metric("Subject", selected_profile[2])
        col2.metric("Target Days", selected_profile[5])
        col3.metric("Daily Minutes", selected_profile[6])

        st.write(f"**Learning goal:** {selected_profile[3]}")
        st.write(f"**Skill level:** {selected_profile[4]}")

        plans = load_plans(selected_id)

        st.subheader("Saved Study Plans")

        if plans:
            for plan_id, plan_json, created_at in plans:
                with st.expander(f"Plan created: {created_at}"):
                    try:
                        saved_plan = json.loads(plan_json)
                        st.write(saved_plan.get("overview", "Study plan"))

                        for day_item in saved_plan.get("days", []):
                            st.markdown(
                                f"**Day {day_item.get('day', '?')}: "
                                f"{day_item.get('topic', 'Topic')}**"
                            )
                            st.write(
                                day_item.get("practice_task", "Review the topic.")
                            )
                    except (json.JSONDecodeError, TypeError):
                        st.warning("This saved plan could not be displayed.")
        else:
            st.info("No saved plans are available for this profile.")

        attempts = load_attempts(selected_id)

        st.subheader("Quiz Performance")

        if attempts:
            total_quizzes = len(attempts)
            total_questions = sum(row[3] for row in attempts)
            total_correct = sum(row[2] for row in attempts)
            accuracy = (
                round((total_correct / total_questions) * 100)
                if total_questions else 0
            )

            col1, col2, col3 = st.columns(3)
            col1.metric("Quizzes Completed", total_quizzes)
            col2.metric("Questions Answered", total_questions)
            col3.metric("Overall Accuracy", f"{accuracy}%")

            st.progress(accuracy / 100)

            st.markdown("### Attempt History")

            for subject_name, topic_name, score, total, wrong_json, created_at in attempts:
                with st.expander(
                    f"{topic_name} — {score}/{total} ({created_at})"
                ):
                    wrong_topics = json.loads(wrong_json)
                    st.write(f"**Subject:** {subject_name}")
                    st.write(f"**Score:** {score}/{total}")

                    if wrong_topics:
                        st.write("**Concepts to review:**")
                        for weak_topic in sorted(set(wrong_topics)):
                            st.write(f"- {weak_topic}")
                    else:
                        st.write("All questions were answered correctly.")

            chart_rows = [
                {
                    "Quiz": f"{row[1]} ({index + 1})",
                    "Accuracy (%)": round((row[2] / row[3]) * 100)
                    if row[3] else 0
                }
                for index, row in enumerate(reversed(attempts))
            ]

            st.markdown("### Quiz Accuracy Over Time")
            st.line_chart(
                chart_rows,
                x="Quiz",
                y="Accuracy (%)"
            )

        else:
            st.info(
                "Complete a practice quiz to see your score, accuracy, "
                "and progress history here."
            )


# --------------------------------------------------
# FOOTER
# --------------------------------------------------

st.divider()
st.caption(
    "AI Personalized Learning Coach | Python • Streamlit • Groq API • SQLite"
)
st.caption(
    "AI-generated educational content may contain errors. "
    "Review important information and use the quiz feedback as a learning aid."
)
