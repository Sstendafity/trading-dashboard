import streamlit as st
import datetime

SESSION_TIMEOUT_MINUTES = 15

def check_password():
    if st.session_state.get("password_correct"):
        last_active = st.session_state.get("last_activity")
        if last_active:
            elapsed_minutes = (datetime.datetime.now() - last_active).total_seconds() / 60
            if elapsed_minutes > SESSION_TIMEOUT_MINUTES:
                st.session_state["password_correct"] = False
                st.session_state["session_expired"] = True
            else:
                st.session_state["last_activity"] = datetime.datetime.now()

    def password_entered():
        if st.session_state["password"] == st.secrets["APP_PASSWORD"]:
            st.session_state["password_correct"] = True
            st.session_state["last_activity"] = datetime.datetime.now()
            st.session_state["session_expired"] = False
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    if not st.session_state.get("password_correct"):
        st.title("🔒 Access Restricted")
        st.text_input("Enter Password", type="password", on_change=password_entered, key="password")

        if st.session_state.get("session_expired"):
            st.warning(f"⏱️ Session expired after {SESSION_TIMEOUT_MINUTES} minutes of inactivity. Please log in again.")
        elif "password_correct" in st.session_state and not st.session_state["password_correct"]:
            st.error("🚫 Incorrect password.")

        return False

    return True