import streamlit as st
import datetime

# --- LOGIN GATEKEEPER ---
# Define how many minutes of inactivity trigger a logout
SESSION_TIMEOUT_MINUTES = 5 

def check_password():
    """Returns `True` if the user entered the correct password and session is valid."""
    
    # 1. Check for inactivity timeout first if they are already logged in
    if st.session_state.get("password_correct"):
        last_active = st.session_state.get("last_activity")
        if last_active:
            elapsed_minutes = (datetime.datetime.now() - last_active).total_seconds() / 60
            if elapsed_minutes > SESSION_TIMEOUT_MINUTES:
                # Time is up. Revoke access.
                st.session_state["password_correct"] = False
                st.session_state["session_expired"] = True
            else:
                # They are active. Reset the clock.
                st.session_state["last_activity"] = datetime.datetime.now()

    def password_entered():
        """Checks whether a password entered by the user is correct."""
        if st.session_state["password"] == st.secrets["APP_PASSWORD"]:
            st.session_state["password_correct"] = True
            st.session_state["last_activity"] = datetime.datetime.now() # Start the clock
            st.session_state["session_expired"] = False
            del st.session_state["password"]  # Don't store the password
        else:
            st.session_state["password_correct"] = False
    
    # ... existing password_entered function ...

    # --- ADD THIS: Force the browser to refresh after the timeout ---
    if st.session_state.get("password_correct"):
        # Convert minutes to seconds for the HTML refresh tag
        refresh_seconds = SESSION_TIMEOUT_MINUTES * 60
        st.markdown(f'<meta http-equiv="refresh" content="{refresh_seconds}">', unsafe_allow_html=True)

    # 2. Render the login screen if they are not authenticated
    if not st.session_state.get("password_correct"):
        st.title("🔒 Access Restricted")
        st.text_input("Enter Password", type="password", on_change=password_entered, key="password")
        
        if st.session_state.get("session_expired"):
            st.warning(f"⏱️ Session expired after {SESSION_TIMEOUT_MINUTES} minutes of inactivity. Please log in again.")
        elif "password_correct" in st.session_state and not st.session_state["password_correct"]:
            st.error("🚫 Incorrect password.")
        
        return False
        
    return True