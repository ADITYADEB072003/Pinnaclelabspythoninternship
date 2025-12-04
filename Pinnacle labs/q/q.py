# app.py
import streamlit as st
from pymongo import MongoClient
from datetime import datetime
import hashlib
import json
import os
from dotenv import load_dotenv
from bson import ObjectId
import pandas as pd

# -------------------------
# Load .env file
# -------------------------
load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
SALT = os.getenv("SALT", "CHANGE_THIS_SALT")
DB_NAME = os.getenv("DB_NAME")

# -------------------------
# DB helpers
# -------------------------
def get_db():
    if not MONGO_URI:
        st.error("MongoDB URI missing. Add it to your .env file.")
        st.stop()

    client = MongoClient(MONGO_URI)

    # 1) If DB_NAME provided in .env -> use it
    if DB_NAME:
        return client[DB_NAME]

    # 2) Try to use the default database embedded in the URI
    try:
        db = client.get_default_database()
        if db is not None:
            return db
    except Exception:
        pass

    # 3) Fallback to a safe default
    fallback = "quizdb"
    st.warning(
        f"No default DB found in URI and DB_NAME not set — using fallback database '{fallback}'."
        " To avoid this, include the DB in your MONGO_URI (e.g. .../quizdb) or set DB_NAME in .env."
    )
    return client[fallback]

db = get_db()

def hash_password(password):
    return hashlib.sha256((SALT + password).encode()).hexdigest()

# -------------------------
# User Operations
# -------------------------
def create_user(username, password, role):
    users = db.users
    if users.find_one({"username": username}):
        return False, "Username already exists."

    users.insert_one({
        "username": username,
        "password_hash": hash_password(password),
        "role": role
    })
    return True, "User created successfully."

def authenticate(username, password):
    users = db.users
    u = users.find_one({"username": username})
    if u and u["password_hash"] == hash_password(password):
        return {"username": u["username"], "role": u["role"]}
    return None

# -------------------------
# Questions Operations
# -------------------------
def add_question(course_code, question, options, answer, marks):
    db.questions.insert_one({
        "course_code": course_code.upper(),
        "question": question,
        "options": options,
        "answer": answer,
        "marks": marks
    })

def get_questions(course_code):
    return list(db.questions.find({"course_code": course_code.upper()}))

def save_attempt(username, course, score, max_score, details):
    db.attempts.insert_one({
        "username": username,
        "course_code": course.upper(),
        "score": score,
        "max_score": max_score,
        "details": details,
        "timestamp": datetime.utcnow().isoformat()
    })

# -------------------------
# Extra helper functions
# -------------------------

def delete_question(qid):
    """Delete a question by its ObjectId string."""
    try:
        db.questions.delete_one({"_id": ObjectId(qid)})
        return True
    except Exception:
        return False


def update_question(qid, course_code, question, options, answer, marks):
    """Update an existing question document."""
    db.questions.update_one(
        {"_id": ObjectId(qid)},
        {
            "$set": {
                "course_code": course_code.upper(),
                "question": question,
                "options": options,
                "answer": answer,
                "marks": marks,
            }
        },
    )


def export_attempts_csv(course_code):
    """Return CSV (string) of attempts for a course code."""
    rows = list(db.attempts.find({"course_code": course_code.upper()}))
    if not rows:
        return None
    # Normalize and flatten
    out = []
    for r in rows:
        entry = {
            "username": r.get("username"),
            "course_code": r.get("course_code"),
            "score": r.get("score"),
            "max_score": r.get("max_score"),
            "timestamp": r.get("timestamp"),
        }
        # add per-question details as JSON string
        entry["details"] = json.dumps(r.get("details", {}))
        out.append(entry)
    df = pd.DataFrame(out)
    return df.to_csv(index=False)


def question_stats(course_code):
    """Compute basic analytics: avg score, attempts count, per-question accuracy."""
    attempts = list(db.attempts.find({"course_code": course_code.upper()}))
    if not attempts:
        return None
    avg = sum(a.get("score", 0) for a in attempts) / len(attempts)
    counts = {}
    for a in attempts:
        details = a.get("details") or {}
        answers = details.get("answers") if isinstance(details, dict) else None
        if not answers and isinstance(details, list):
            answers = details
        if not answers:
            continue
        for ans in answers:
            qtext = ans.get("question")
            rec = counts.setdefault(qtext, {"correct": 0, "total": 0})
            rec["total"] += 1
            if ans.get("is_correct"):
                rec["correct"] += 1
    accuracy = {q: (v["correct"] / v["total"]) for q, v in counts.items() if v["total"] > 0}
    return {"avg_score": avg, "attempts": len(attempts), "question_accuracy": accuracy}

# -------------------------
# Streamlit UI
# -------------------------
st.title("Quiz App (Student + Teacher)")

if "user" not in st.session_state:
    st.session_state.user = None

with st.sidebar:
    st.header("Authentication")
    if st.session_state.user:
        st.success(f"Logged in as {st.session_state.user['username']} ({st.session_state.user['role']})")
        if st.button("Logout"):
            st.session_state.user = None
            st.rerun()
    else:
        mode = st.radio("Choose Mode", ["Login", "Signup"])
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")

        if mode == "Signup":
            role = st.selectbox("Role", ["student", "teacher"])
            if st.button("Signup"):
                ok, msg = create_user(username, password, role)
                st.info(msg)

        if mode == "Login":
            if st.button("Login"):
                user = authenticate(username, password)
                if user:
                    st.session_state.user = user
                    st.rerun()
                else:
                    st.error("Invalid credentials")

if not st.session_state.user:
    st.stop()

user = st.session_state.user

# -------------------------
# Teacher Panel
# -------------------------
if user["role"] == "teacher":
    st.header("Teacher Panel")

    st.subheader("➕ Add Question")
    course = st.text_input("Course Code (e.g., CS101)", key="teacher_add_course")
    question = st.text_area("Question", key="teacher_add_q")
    options_raw = st.text_area("Options (comma separated)", key="teacher_add_opts")
    answer = st.text_input("Correct Answer", key="teacher_add_ans")
    marks = st.number_input("Marks", value=1.0, key="teacher_add_marks")

    if st.button("Add Question", key="teacher_add_btn"):
        options = [o.strip() for o in options_raw.split(",") if o.strip()]
        if not course or not question or not options or not answer:
            st.error("Fill all fields before adding a question.")
        elif answer not in options:
            st.error("Correct answer MUST be one of the options.")
        else:
            add_question(course, question, options, answer, marks)
            st.success("Question added successfully!")

    st.markdown("---")
    st.subheader("📝 Manage Questions")
    manage_course = st.text_input("Enter Course Code to manage/list questions", key="teacher_manage_course")
    if manage_course:
        qs = list(db.questions.find({"course_code": manage_course.upper()}))
        if not qs:
            st.info("No questions for this course.")
        else:
            for q in qs:
                qid = str(q.get("_id"))
                with st.expander(f"Q: {q.get('question')[:120]}"):
                    st.write("**Options:**", ", ".join(q.get("options", [])))
                    st.write("**Answer:**", q.get("answer"))
                    st.write("**Marks:**", q.get("marks"))

                    col1, col2, col3 = st.columns([1,1,1])
                    if col1.button("Edit", key=f"edit_{qid}"):
                        # populate temporary session keys for editing
                        st.session_state[f"edit_course_{qid}"] = q.get("course_code")
                        st.session_state[f"edit_question_{qid}"] = q.get("question")
                        st.session_state[f"edit_options_{qid}"] = ", ".join(q.get("options", []))
                        st.session_state[f"edit_answer_{qid}"] = q.get("answer")
                        st.session_state[f"edit_marks_{qid}"] = float(q.get("marks",1))

                    if col2.button("Delete", key=f"delete_{qid}"):
                        if delete_question(qid):
                            st.success("Question deleted.")
                            st.rerun()
                        else:
                            st.error("Failed to delete question.")

                    # Edit area (show if session keys exist)
                    if f"edit_course_{qid}" in st.session_state:
                        st.markdown("**Edit Question**")
                        ecourse = st.text_input("Course Code", key=f"edit_course_{qid}")
                        equestion = st.text_area("Question", key=f"edit_question_{qid}")
                        eoptions = st.text_area("Options (comma separated)", key=f"edit_options_{qid}")
                        eanswer = st.text_input("Correct Answer", key=f"edit_answer_{qid}")
                        emarks = st.number_input("Marks", value=st.session_state.get(f"edit_marks_{qid}",1.0), key=f"edit_marks_input_{qid}")
                        if st.button("Save Changes", key=f"save_{qid}"):
                            opts = [o.strip() for o in eoptions.split(",") if o.strip()]
                            if eanswer not in opts:
                                st.error("Correct answer must be one of the options.")
                            else:
                                update_question(qid, ecourse, equestion, opts, eanswer, emarks)
                                # clear edit keys
                                for k in list(st.session_state.keys()):
                                    if k.startswith(f"edit_") and k.endswith(f"_{qid}") or k == f"edit_marks_{qid}":
                                        del st.session_state[k]
                                st.success("Question updated.")
                                st.rerun()

    st.markdown("---")
    st.subheader("📥 Export Attempts / Basic Analytics")
    export_course = st.text_input("Course Code for export/analytics", key="teacher_export_course")
    if export_course:
        csv_data = export_attempts_csv(export_course)
        stats = question_stats(export_course)

        if csv_data:
            st.download_button("Download Attempts CSV", data=csv_data, file_name=f"{export_course}_attempts.csv", mime="text/csv")
        else:
            st.info("No attempts to export for this course.")

        # Show summary table of students and their scores
        attempts_for_students = list(db.attempts.find({"course_code": export_course.upper()}))
        if attempts_for_students:
            students_rows = []
            for a in attempts_for_students:
                students_rows.append({
                    "username": a.get("username"),
                    "score": a.get("score"),
                    "max_score": a.get("max_score"),
                    "timestamp": a.get("timestamp"),
                })
            students_df = pd.DataFrame(students_rows)
            if not students_df.empty:
                students_df = students_df.sort_values(by=["score"], ascending=False)
                st.subheader("Students Summary")
                st.table(students_df)
                # Also show detailed attempts (one row per attempt) and allow CSV download
                st.subheader("Detailed Attempts")
                attempts_rows = []
                for a in attempts_for_students:
                    attempts_rows.append({
                        "username": a.get("username"),
                        "score": a.get("score"),
                        "max_score": a.get("max_score"),
                        "timestamp": a.get("timestamp"),
                    })
                attempts_df = pd.DataFrame(attempts_rows)
                if not attempts_df.empty:
                    attempts_df = attempts_df.sort_values(by=["timestamp"], ascending=False)
                    st.dataframe(attempts_df)
                    csv_attempts = attempts_df.to_csv(index=False)
                    st.download_button("Download detailed attempts CSV", data=csv_attempts, file_name=f"{export_course}_detailed_attempts.csv", mime="text/csv")

        if stats:
            st.metric("Average Score", f"{stats['avg_score']:.2f}")
            st.metric("Total Attempts", stats["attempts"])
            st.subheader("Per-question Accuracy")
            if stats["question_accuracy"]:
                acc_df = pd.DataFrame([{"question": q, "accuracy": acc} for q, acc in stats["question_accuracy"].items()])
                st.table(acc_df)
            else:
                st.info("No detailed per-question data available.")

# -------------------------
# Student Panel
# -------------------------
if user["role"] == "student":
    st.header("Student Panel")
    course = st.text_input("Course Code to Attempt")

    if course:
        questions = get_questions(course)

        if not questions:
            st.warning("No questions available for this course.")
        else:
            if "index" not in st.session_state:
                st.session_state.index = 0
                st.session_state.score = 0
                st.session_state.answers = []

            q = questions[st.session_state.index]
            st.subheader(f"Question {st.session_state.index + 1}/{len(questions)}")
            st.write(q["question"])

            choice = st.radio("Options", q["options"])

            if st.button("Submit Answer"):
                correct = choice == q["answer"]
                if correct:
                    st.session_state.score += q["marks"]

                st.session_state.answers.append({
                    "question": q["question"],
                    "selected": choice,
                    "correct": q["answer"],
                    "is_correct": correct
                })

                if st.session_state.index + 1 < len(questions):
                    st.session_state.index += 1
                    st.rerun()
                else:
                    save_attempt(user["username"], course, st.session_state.score,
                                 sum(q["marks"] for q in questions),
                                 st.session_state.answers)
                    st.success(f"Quiz Finished! Score: {st.session_state.score}")

                    # Reset for next quiz
                    st.session_state.index = 0
                    st.session_state.score = 0
                    st.session_state.answers = []