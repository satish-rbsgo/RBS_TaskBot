import streamlit as st
from supabase import create_client, Client
import pandas as pd
from datetime import datetime, date, timedelta

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="RBS TaskHub", layout="wide", page_icon="🚀")

# --- CONFIGURATION ---
COMPANY_DOMAIN = "@rbsgo.com"
ADMIN_EMAIL = "msk@rbsgo.com"

# --- TEAM ROSTER ---
TEAM_MEMBERS = [
    "msk@rbsgo.com",
    "praveen@rbsgo.com",
    "arjun@rbsgo.com",
    "prasanna@rbsgo.com",
    "chris@rbsgo.com",
    "sarah@rbsgo.com"
]

# --- SECURE CONNECTION ---
try:
    SUPABASE_URL = st.secrets["SUPABASE_URL"]
    SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
except FileNotFoundError:
    st.error("🚨 Secrets not found! Please configure secrets on Streamlit Cloud.")
    st.stop()

@st.cache_resource
def init_supabase():
    return create_client(SUPABASE_URL, SUPABASE_KEY)

supabase = init_supabase()

# --- DATABASE FUNCTIONS ---
def add_task(created_by, assigned_to, task_desc, priority, due_date):
    try:
        # LOGIC: If date is missing, default to TODAY
        final_date = str(due_date) if due_date else str(date.today())
        
        data = {
            "created_by": created_by,
            "assigned_to": assigned_to,
            "task_desc": task_desc,
            "status": "Open",
            "priority": priority,
            "due_date": final_date,
            "staff_remarks": "",
            "manager_remarks": ""
        }
        supabase.table("tasks").insert(data).execute()
        return True
    except Exception as e:
        st.error(f"Error: {e}")
        return False

def get_tasks(user_email, is_admin=False):
    query = supabase.table("tasks").select("*")
    if not is_admin:
        query = query.eq("assigned_to", user_email)
    
    response = query.execute()
    return pd.DataFrame(response.data) if response.data else pd.DataFrame()

def update_task_status(task_id, new_status, remarks=None):
    try:
        data = {"status": new_status}
        if remarks:
            data["staff_remarks"] = remarks
        supabase.table("tasks").update(data).eq("id", task_id).execute()
        return True
    except Exception as e:
        return False

# --- MAIN APP ---
def main():
    if 'logged_in' not in st.session_state:
        st.session_state['logged_in'] = False

    # --- LOGIN SCREEN ---
    if not st.session_state['logged_in']:
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            st.title("🚀 RBS TaskHub")
            with st.container(border=True):
                email = st.text_input("Enter Work Email:")
                if st.button("Login", use_container_width=True):
                    if email.endswith(COMPANY_DOMAIN):
                        st.session_state['logged_in'] = True
                        st.session_state['user'] = email
                        st.rerun()
                    else:
                        st.error(f"Restricted Access. {COMPANY_DOMAIN} only.")

    # --- MAIN DASHBOARD ---
    else:
        current_user = st.session_state['user']
        is_admin = (current_user == ADMIN_EMAIL)
        
        # --- SIDEBAR NAVIGATION (The Control Center) ---
        with st.sidebar:
            st.title("🎛️ Menu")
            st.info(f"👤 {current_user.split('@')[0].title()}")
            
            # Navigation Mode
            nav_mode = st.radio("Go To:", ["📊 Dashboard", "➕ Create Task", "🤖 Task Assistant"])
            
            st.divider()
            if st.button("Logout", use_container_width=True):
                st.session_state['logged_in'] = False
                st.rerun()

        # --- VIEW 1: CREATE TASK (Moved to Sidebar/Separate View) ---
        if nav_mode == "➕ Create Task":
            st.header("✨ Create New Task")
            with st.container(border=True):
                c1, c2 = st.columns([1, 3])
                with c1:
                    assign_type = st.radio("Assign To:", ["Myself", "Teammate"], horizontal=True)
                    if assign_type == "Teammate":
                        peers = [m for m in TEAM_MEMBERS if m != current_user]
                        target_user = st.selectbox("Select User", peers)
                    else:
                        target_user = current_user
                
                with c2:
                    desc = st.text_input("Task Description", placeholder="e.g. Update Oracle Fusion Posting")
                
                c3, c4 = st.columns(2)
                with c3:
                    prio = st.selectbox("Priority", ["🔥 High", "⚡ Medium", "🧊 Low"])
                with c4:
                    # DATE LOGIC: Ensure it can be empty (defaults to None if cleared)
                    due = st.date_input("Target Date (Default: Today)", value=None)
                
                st.write("")
                if st.button("🚀 Confirm & Add Task", type="primary", use_container_width=True):
                    if desc:
                        if add_task(current_user, target_user, desc, prio, due):
                            st.balloons() # Nice visual effect
                            st.success("✅ Task Added Successfully!")
                            # Wait 1 second then go back to dashboard? Or just stay.
                            # For now, we show success. User can click Dashboard to see it.
                    else:
                        st.warning("⚠️ Please enter a description.")

        # --- VIEW 2: TASK ASSISTANT ---
        elif nav_mode == "🤖 Task Assistant":
            st.header("💬 AI Assistant")
            st.info("Ask questions like: 'How many pending tasks?' or 'Show overdue items'.")
            query = st.text_input("Type your question here...")
            if query:
                # Simple logic for now
                st.write("🤖 Analysis: This feature is connecting to your task data...")
                # (We will expand this logic in next steps)

        # --- VIEW 3: DASHBOARD (Default) ---
        elif nav_mode == "📊 Dashboard":
            st.title("📅 Your Schedule")

            # FETCH DATA
            df = get_tasks(current_user, is_admin)
            
            if not df.empty:
                # DATE PROCESSING
                df['due_date'] = pd.to_datetime(df['due_date'], errors='coerce')
                today_ts = pd.Timestamp.now().normalize()
                
                # Default Filter: TODAY
                if 'filter_view' not in st.session_state:
                    st.session_state['filter_view'] = 'Today'

                # FILTER BUTTONS
                c1, c2, c3, c4 = st.columns(4)
                if c1.button("⚡ Today"): st.session_state['filter_view'] = 'Today'
                if c2.button("📅 Tomorrow"): st.session_state['filter_view'] = 'Tomorrow'
                if c3.button("🚨 Overdue"): st.session_state['filter_view'] = 'Overdue'
                if c4.button("📂 All Pending"): st.session_state['filter_view'] = 'All'

                # FILTER LOGIC
                view = st.session_state['filter_view']
                active_df = df[df['status'] != 'Completed'].copy() # Only show OPEN tasks
                
                if view == 'Today':
                    filtered_df = active_df[active_df['due_date'] == today_ts]
                    st.caption("Focus Mode: Tasks Due Today")
                elif view == 'Tomorrow':
                    filtered_df = active_df[active_df['due_date'] == today_ts + pd.Timedelta(days=1)]
                    st.caption("Planning Mode: Tomorrow")
                elif view == 'Overdue':
                    filtered_df = active_df[active_df['due_date'] < today_ts]
                    st.caption("Action Mode: Overdue Items")
                else:
                    filtered_df = active_df
                    st.caption("Overview Mode: All Pending")

                # DISPLAY CARDS
                if filtered_df.empty:
                    st.success("🎉 No tasks in this view! You are all caught up.")
                
                filtered_df = filtered_df.sort_values(by=["priority"], ascending=True)
                
                for index, row in filtered_df.iterrows():
                    # CARD DESIGN
                    with st.container(border=True):
                        c1, c2, c3 = st.columns([4, 2, 1])
                        
                        with c1:
                            # Task Title & Info
                            st.markdown(f"### {row['task_desc']}")
                            display_date = row['due_date'].strftime('%Y-%m-%d') if pd.notnull(row['due_date']) else "No Date"
                            st.caption(f"📅 Due: {display_date} | Priority: {row['priority']}")
                            if row['staff_remarks']:
                                st.info(f"📝 Note: {row['staff_remarks']}")

                        with c2:
                            # Quick Remark
                            new_rem = st.text_input("Add Remark", key=f"rem_{row['id']}", placeholder="Update status...")
                            if new_rem:
                                update_task_status(row['id'], row['status'], new_rem)
                                st.toast("Remark Saved")

                        with c3:
                            # THE MAGIC "DONE" BUTTON
                            st.write("") # Spacer to align button down
                            if st.button("✅ Done", key=f"done_{row['id']}", type="primary", use_container_width=True):
                                update_task_status(row['id'], "Completed")
                                st.balloons()
                                st.rerun() # INSTANT REFRESH
            else:
                st.info("👋 Welcome! Go to 'Create Task' in the sidebar to start.")

if __name__ == "__main__":
    main()
