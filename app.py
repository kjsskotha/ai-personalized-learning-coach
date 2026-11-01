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
