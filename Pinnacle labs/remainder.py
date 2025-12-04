#!/usr/bin/env python3
"""
Streamlit Calendar & Reminder App using MongoDB
- Run with: streamlit run remainder.py
- Stores reminders in MongoDB (MONGO_URI, MONGO_DB, MONGO_COLLECTION from .env)

This version adds:
- A homepage with a single toggle (Login / Sign up) for the auth UI.
- Per-user reminders and calendar (each reminder stored with `user_id`).
- Reminder queries / counts are scoped to the logged-in user.

Dependencies: streamlit, pymongo, python-dotenv, (optional) werkzeug
"""
import os
import streamlit as st
import calendar
import datetime
from pymongo import MongoClient
from bson.objectid import ObjectId
from dotenv import load_dotenv
load_dotenv()
st.set_page_config(page_title="Calendar & Reminders", layout="wide")

# Config (from env or defaults)
MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017/")
DB_NAME = os.environ.get("MONGO_DB", "calendar_app")
COLLECTION_NAME = os.environ.get("MONGO_COLLECTION", "reminders")
USERS_COLLECTION = os.environ.get("MONGO_USERS_COLLECTION", "users")

# Hashing helpers: prefer werkzeug, fallback to hashlib
try:
    from werkzeug.security import generate_password_hash, check_password_hash
    _USE_WERKZEUG = True
except Exception:
    import hashlib
    _USE_WERKZEUG = False

    def generate_password_hash(password: str) -> str:
        # note: simple fallback; in production use bcrypt/werkzeug
        salt = os.environ.get('PW_SALT', 'change_this_salt')
        return hashlib.sha256((salt + password).encode('utf-8')).hexdigest()

    def check_password_hash(hashed: str, password: str) -> bool:
        salt = os.environ.get('PW_SALT', 'change_this_salt')
        return hashed == hashlib.sha256((salt + password).encode('utf-8')).hexdigest()

# Helpers: DB connection cached for Streamlit
@st.cache_resource
def get_db():
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]
    return db

@st.cache_resource
def get_collection():
    db = get_db()
    coll = db[COLLECTION_NAME]
    try:
        # index by user and date for faster per-user queries
        coll.create_index([("user_id", 1), ("date", 1)])
    except Exception:
        pass
    return coll

@st.cache_resource
def get_users_collection():
    db = get_db()
    users = db[USERS_COLLECTION]
    try:
        users.create_index([("username", 1)], unique=True)
    except Exception:
        pass
    return users

coll = get_collection()
users_coll = get_users_collection()

# User management
def create_user(username, password):
    username = username.strip().lower()
    if not username or not password:
        return None, "Username and password required"
    if users_coll.find_one({"username": username}):
        return None, "Username already exists"
    hashed = generate_password_hash(password)
    doc = {"username": username, "password": hashed, "created_at": datetime.datetime.utcnow()}
    res = users_coll.insert_one(doc)
    return str(res.inserted_id), None

def authenticate_user(username, password):
    username = username.strip().lower()
    user = users_coll.find_one({"username": username})
    if not user:
        return None
    if check_password_hash(user.get("password", ""), password):
        return user
    return None

# Streamlit session state defaults for calendar and auth
if "year" not in st.session_state:
    st.session_state.year = datetime.date.today().year
if "month" not in st.session_state:
    st.session_state.month = datetime.date.today().month
if "selected_date" not in st.session_state:
    st.session_state.selected_date = None
if "edit_id" not in st.session_state:
    st.session_state.edit_id = None
if "user" not in st.session_state:
    st.session_state.user = None  # will hold dict-like user record

# UI helpers
def prev_month():
    y = st.session_state.year
    m = st.session_state.month - 1
    if m < 1:
        m = 12
        y -= 1
    st.session_state.year = y
    st.session_state.month = m

def next_month():
    y = st.session_state.year
    m = st.session_state.month + 1
    if m > 12:
        m = 1
        y += 1
    st.session_state.year = y
    st.session_state.month = m

# Calendar/Reminders functions (now per-user)
def reminders_for_date(date_obj):
    key = date_obj.isoformat()
    user_id = st.session_state.user.get("_id")
    docs = list(coll.find({"date": key, "user_id": user_id}))
    docs.sort(key=lambda d: d.get("time") or "99:99")
    return docs

def add_reminder(date_obj, title, time_str, notes):
    user_id = st.session_state.user.get("_id")
    doc = {
        "user_id": user_id,
        "date": date_obj.isoformat(),
        "title": title,
        "time": time_str or "",
        "notes": notes or "",
        "created_at": datetime.datetime.utcnow()
    }
    res = coll.insert_one(doc)
    return str(res.inserted_id)

def update_reminder(reminder_id, title, time_str, notes):
    user_id = st.session_state.user.get("_id")
    coll.update_one({"_id": ObjectId(reminder_id), "user_id": user_id}, {"$set": {"title": title, "time": time_str or "", "notes": notes or ""}})

def delete_reminder(reminder_id):
    user_id = st.session_state.user.get("_id")
    coll.delete_one({"_id": ObjectId(reminder_id), "user_id": user_id})

# Top bar / Homepage: a simple landing page with a toggle for Login / Signup
st.markdown("<style>footer {visibility: hidden;} </style>", unsafe_allow_html=True)

# If user logged in show small top info and logout
if st.session_state.user:
    user_display = st.session_state.user.get("username", "user")
    col_top = st.columns([8,1,1])
    with col_top[1]:
        if st.button("Logout"):
            st.session_state.user = None
            st.rerun()
    with col_top[0]:
        st.markdown(f"<div style='text-align:left; font-size:14px;'>Logged in as **{user_display}**</div>", unsafe_allow_html=True)

# If not logged in, show homepage with toggle (Login / Signup)
if not st.session_state.user:
    st.markdown("# Welcome — Calendar & Reminders")
    st.markdown("Select `Login` if you already have an account, or `Sign up` to create one.")
    auth_mode = st.radio("Auth action:", ["Login", "Sign up"], index=0, horizontal=True)

    if auth_mode == "Login":
        st.markdown("### Login")
        login_username = st.text_input("Username", key="login_username")
        login_password = st.text_input("Password", type="password", key="login_password")
        if st.button("Login"):
            user = authenticate_user(login_username, login_password)
            if user:
                st.session_state.user = {"_id": str(user.get("_id")), "username": user.get("username")}
                st.success("Logged in")
                st.rerun()
            else:
                st.error("Invalid username or password")
    else:
        st.markdown("### Sign up")
        su_username = st.text_input("New username", key="su_username")
        su_password = st.text_input("New password", type="password", key="su_password")
        su_password2 = st.text_input("Confirm password", type="password", key="su_password2")
        if st.button("Sign up"):
            if not su_username.strip() or not su_password:
                st.error("Username and password required")
            elif su_password != su_password2:
                st.error("Passwords do not match")
            else:
                _id, err = create_user(su_username, su_password)
                if err:
                    st.error(err)
                else:
                    st.success("Account created — you can now login")
    st.stop()

# At this point user is authenticated — show their personal calendar + reminders

# Title and controls
col1, col2, col3 = st.columns([1,6,1])
with col1:
    if st.button("◀ Prev"):
        prev_month()
with col2:
    month_title = f"📅 {calendar.month_name[st.session_state.month]} {st.session_state.year}"
    st.markdown(f"<div style='text-align:center;'><h1 style='margin:6px 0;'>{month_title}</h1></div>", unsafe_allow_html=True)
with col3:
    if st.button("Next ▶"):
        next_month()

# Layout: left calendar, right reminders
cal_col, rem_col = st.columns([2,1])

# Draw calendar (counts are per-user)
with cal_col:
    year = st.session_state.year
    month = st.session_state.month
    cal = calendar.Calendar(firstweekday=0)
    month_days = cal.monthdatescalendar(year, month)

    weekdays = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
    header_cols = st.columns(len(weekdays))
    for i, d in enumerate(weekdays):
        with header_cols[i]:
            st.markdown(f"**{d}**")

    for week in month_days:
        cols = st.columns(len(week))
        for i, day in enumerate(week):
            is_current = (day.month == month)
            key = day.isoformat()
            label = str(day.day)
            # mark if reminders exist for this user/date
            try:
                user_id = st.session_state.user.get("_id")
                if coll.count_documents({"date": key, "user_id": user_id}) > 0:
                    label += " •"
            except Exception:
                pass
            btn_key = f"btn-{key}"
            if is_current:
                if cols[i].button(label, key=btn_key):
                    st.session_state.selected_date = day
                    st.session_state.edit_id = None
            else:
                cols[i].button(label, key=btn_key, disabled=True)

# Reminders panel (scoped to user)
with rem_col:
    st.markdown("### Reminders")
    if st.session_state.selected_date:
        sel = st.session_state.selected_date
        st.markdown(f"**Selected:** {sel.isoformat()}")
        items = reminders_for_date(sel)
        if not items:
            st.info("No reminders for this date.")
        else:
            for it in items:
                rid = str(it.get("_id"))
                t = it.get("time") or "--:--"
                title = it.get("title") or "(no title)"
                notes = it.get("notes") or ""
                st.markdown(f"**{t} — {title}**")
                if notes:
                    st.markdown(f"> {notes}")
                cols = st.columns([1,1,6])
                if cols[0].button("Edit", key=f"edit-{rid}"):
                    st.session_state.edit_id = rid
                    st.session_state.selected_date = sel
                if cols[1].button("Delete", key=f"del-{rid}"):
                    delete_reminder(rid)
                    st.rerun()
                st.markdown("---")

        st.markdown("### Add / Edit reminder")
        if st.session_state.edit_id:
            doc = coll.find_one({"_id": ObjectId(st.session_state.edit_id), "user_id": st.session_state.user.get("_id")})
            # if doc is None (deleted or not owned) fallback to empty
            if doc:
                default_title = doc.get("title", "")
                default_time = doc.get("time", "")
                default_notes = doc.get("notes", "")
            else:
                default_title = ""
                default_time = ""
                default_notes = ""
        else:
            default_title = ""
            default_time = ""
            default_notes = ""

        with st.form(key="rem_form"):
            title = st.text_input("Title", value=default_title)
            time_str = st.text_input("Time (HH:MM)", value=default_time)
            notes = st.text_area("Notes", value=default_notes)
            submitted = st.form_submit_button("Save")
            if submitted:
                if not title.strip():
                    st.error("Title is required")
                else:
                    if st.session_state.edit_id:
                        update_reminder(st.session_state.edit_id, title.strip(), time_str.strip(), notes.strip())
                        st.success("Reminder updated")
                        st.session_state.edit_id = None
                        st.rerun()
                    else:
                        add_reminder(st.session_state.selected_date, title.strip(), time_str.strip(), notes.strip())
                        st.success("Reminder added")
                        st.rerun()
    else:
        st.info("Select a date on the calendar to view and add reminders.")

# Footer: simple instructions
st.markdown("---")
st.markdown("Built with Streamlit — click a date to manage reminders. Use your .env to configure MongoDB (MONGO_URI, MONGO_DB, MONGO_COLLECTION).")
