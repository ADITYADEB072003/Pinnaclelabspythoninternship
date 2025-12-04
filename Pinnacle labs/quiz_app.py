import streamlit as st

# ---- Quiz data ----
QUESTIONS = [
    {
        "question": "Which keyword is used to define a function in Python?",
        "options": ["func", "def", "function", "lambda"],
        "answer": "def",
        "marks": 1,
    },
    {
        "question": "Which data type is immutable?",
        "options": ["list", "dict", "set", "tuple"],
        "answer": "tuple",
        "marks": 1,
    },
]

# ---- Session state init ----
if "current" not in st.session_state:
    st.session_state.current = 0
if "score" not in st.session_state:
    st.session_state.score = 0
if "finished" not in st.session_state:
    st.session_state.finished = False

st.title("Python Quiz (Streamlit)")

# Restart button
if st.button("Restart quiz"):
    st.session_state.current = 0
    st.session_state.score = 0
    st.session_state.finished = False

# If quiz finished
if st.session_state.finished:
    total = sum(q["marks"] for q in QUESTIONS)
    st.success(f"Quiz finished! Your score: {st.session_state.score} / {total}")
else:
    q = QUESTIONS[st.session_state.current]
    st.subheader(f"Question {st.session_state.current + 1} of {len(QUESTIONS)}")
    st.write(q["question"])

    choice = st.radio("Choose one:", q["options"], index=None)

    if st.button("Submit answer"):
        if choice is None:
            st.warning("Please select an option.")
        else:
            if choice == q["answer"]:
                st.session_state.score += q["marks"]
                st.success("Correct!")
            else:
                st.error(f"Wrong. Correct answer: {q['answer']}")

            if st.session_state.current + 1 < len(QUESTIONS):
                st.session_state.current += 1
                st.rerun()
            else:
                st.session_state.finished = True
                st.rerun()
