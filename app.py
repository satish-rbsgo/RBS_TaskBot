import streamlit as st
from supabase import create_client, Client
import pandas as pd
from datetime import datetime, date, timedelta

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="RBS TaskHub", layout="wide", page_icon="✅")

# --- CONFIGURATION ---
COMPANY_DOMAIN = "@rbsgo.com"
ADMIN_EMAIL = "msk@rbsgo.com"

# --- TEAM ROSTER (Add all emails here) ---
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
        data = {
            "created_by": created_by,
            "assigned_to": assigned_to,
            "task_desc": task_desc,
            "status": "Open",
            "priority": priority,
            "due_date": str(due_date),
            "staff_remarks": "",
            "manager_remarks": ""
        }
        supabase.table("tasks").insert(data).execute()
        return True
    except Exception as e:
        st.error(f"Error: {e}")
        return False

def get_tasks(user_email, is_admin=False):
    # If Admin, fetch EVERYTHING (for Analytics). If User, fetch ONLY assigned to them.
    # But for the "Team Overview", Admin needs to see all.
    query = supabase.table("tasks").select("*")
    if not is_admin:
        query = query.eq("assigned_to", user_email)
    
    response = query.execute()
    return pd.DataFrame(response.data) if response.data else pd.DataFrame()

def update_task(task_id, status, staff_remark, manager_remark):
    try:
        data = {
            "status": status,
            "staff_remarks": staff_remark,
            "manager_remarks": manager_remark
        }
        supabase.table("tasks").update(data).eq("id", task_id).execute()
        return True
    except Exception as e:
        return False

# --- CHATBOT ENGINE (Simple Rule-Based) ---
def chatbot_response(query, df):
    query = query.lower()
    
    # 1. Count Queries
    if "how many" in query or "count" in query:
        if "pending" in query:
            count = len(df[df['status'] != 'Completed'])
            return f"You have {count} pending tasks."
        if "high" in query:
            count = len(df[df['priority'] == '🔥 High'])
            return f"You have {count} High Priority tasks."
            
    # 2. List Queries
    if "show" in query or "list" in query:
        if "today" in query:
            today_str = str(date.today())
            tasks = df[df['due_date'] == today_str]['task_desc'].tolist()
            return "Tasks for Today:\n" + "\n".join([f"- {t}" for t in tasks]) if tasks else "Nothing due today!"
            
    return "I can help! Try asking: 'How many pending tasks?' or 'Show tasks for today'."

# --- MAIN APP ---
def main():
    if 'logged_in' not in st.session_state:
        st.session_state['logged_in'] = False

    # --- LOGIN SCREEN ---
    if not st.session_state['logged_in']:
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            st.title("✅ RBS TaskHub")
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
        
        # Sidebar Profile
        with st.sidebar:
            st.title(f"👤 {current_user.split('@')[0].title()}")
            if is_admin: 
                st.info("⚡ HEAD MODE")
            if st.button("Logout", use_container_width=True):
                st.session_state['logged_in'] = False
                st.rerun()

        st.title("Task Command Center")

        # --- 1. THE TASK CREATOR (Self vs Team) ---
        with st.expander("➕ Create / Assign Task", expanded=False):
            with st.form("new_task_form"):
                c1, c2 = st.columns([1, 3])
                with c1:
                    # The Magic Toggle
                    assign_type = st.radio("Assign To:", ["Myself", "Teammate"], horizontal=True)
                    if assign_type == "Teammate":
                        # Filter out current user from list to avoid confusion
                        peers = [m for m in TEAM_MEMBERS if m != current_user]
                        target_user = st.selectbox("Select User", peers)
                    else:
                        target_user = current_user
                
                with c2:
                    desc = st.text_input("Task Description", placeholder="e.g. Prepare Monthly Report")
                
                c3, c4, c5 = st.columns(3)
                with c3:
                    prio = st.selectbox("Priority", ["🔥 High", "⚡ Medium", "🧊 Low"])
                with c4:
                    due = st.date_input("Target Date", min_value=date.today())
                with c5:
                    st.write("") # Spacer
                    submitted = st.form_submit_button("🚀 Add Task", use_container_width=True)
                
                if submitted and desc:
                    if add_task(current_user, target_user, desc, prio, due):
                        st.toast(f"✅ Task assigned to {target_user}!")
                        st.rerun()

        # --- 2. DATA & FILTERING ---
        df = get_tasks(current_user, is_admin)
        
        if not df.empty:
            # Ensure Date column is standard
            df['due_date'] = pd.to_datetime(df['due_date']).dt.date
            today = date.today()
            
            # --- DATE COUNTS (The "Navigator") ---
            # Calculate counts for the buttons
            overdue_count = len(df[(df['due_date'] < today) & (df['status'] != 'Completed')])
            today_count = len(df[(df['due_date'] == today) & (df['status'] != 'Completed')])
            tomorrow_count = len(df[(df['due_date'] == today + timedelta(days=1)) & (df['status'] != 'Completed')])
            
            # Use Session State to remember which filter is active
            if 'filter_view' not in st.session_state:
                st.session_state['filter_view'] = 'Today'

            # Metric Buttons (Clickable Filters)
            st.write("### 📅 Your Schedule")
            b1, b2, b3, b4 = st.columns(4)
            
            if b1.button(f"🚨 Overdue ({overdue_count})"):
                st.session_state['filter_view'] = 'Overdue'
            if b2.button(f"⚡ Today ({today_count})"):
                st.session_state['filter_view'] = 'Today'
            if b3.button(f"📅 Tomorrow ({tomorrow_count})"):
                st.session_state['filter_view'] = 'Tomorrow'
            if b4.button("📂 Show All"):
                st.session_state['filter_view'] = 'All'

            # --- APPLY FILTER ---
            view = st.session_state['filter_view']
            filtered_df = df.copy()
            
            if view == 'Overdue':
                filtered_df = df[df['due_date'] < today]
                st.warning(f"Displaying {len(filtered_df)} Overdue Tasks")
            elif view == 'Today':
                filtered_df = df[df['due_date'] == today]
                st.success(f"Displaying {len(filtered_df)} Tasks Due Today")
            elif view == 'Tomorrow':
                filtered_df = df[df['due_date'] == today + timedelta(days=1)]
                st.info(f"Displaying {len(filtered_df)} Tasks Due Tomorrow")
            else:
                st.caption("Displaying All Tasks")

            # --- 3. TASK LIST DISPLAY ---
            # Sort: High Priority first
            filtered_df = filtered_df.sort_values(by=["priority"], ascending=True) # Ascending because "🔥" comes after letters
            
            for index, row in filtered_df.iterrows():
                # Card Styling
                card_color = "red" if row['priority'] == '🔥 High' else "grey"
                
                with st.container(border=True):
                    c1, c2, c3, c4 = st.columns([3, 2, 2, 1])
                    
                    with c1:
                        # Title
                        st.markdown(f"**{row['task_desc']}**")
                        # Subtitle
                        assign_label = "Me" if row['assigned_to'] == current_user else row['assigned_to']
                        st.caption(f"👤 {assign_label} | 📅 {row['due_date']} | {row['priority']}")
                    
                    with c2:
                        curr_rem = row['staff_remarks'] if row['staff_remarks'] else ""
                        new_rem = st.text_input("My Remarks", value=curr_rem, key=f"r_{row['id']}")
                    
                    with c3:
                        mgr_rem = row['manager_remarks'] if row['manager_remarks'] else ""
                        new_mgr = st.text_input("Head Reply", value=mgr_rem, key=f"m_{row['id']}", disabled=not is_admin)
                    
                    with c4:
                        status_opts = ["Open", "In Progress", "Pending Info", "Completed"]
                        try:
                            s_idx = status_opts.index(row['status'])
                        except:
                            s_idx = 0
                        new_stat = st.selectbox("Status", status_opts, index=s_idx, key=f"s_{row['id']}", label_visibility="collapsed")
                        
                        if st.button("Update", key=f"btn_{row['id']}"):
                            update_task(row['id'], new_stat, new_rem, new_mgr)
                            st.rerun()
                            
        else:
            st.info("No tasks found. Create one above!")

        # --- 4. TASK ASSISTANT CHATBOT (Bottom Right) ---
        with st.expander("💬 Task Assistant (Beta)", expanded=False):
            user_query = st.text_input("Ask about tasks...", placeholder="e.g. How many pending today?")
            if user_query:
                # We pass the FULL dataframe to the bot so it can count properly
                bot_reply = chatbot_response(user_query, df)
                st.write(f"🤖 **Bot:** {bot_reply}")

if __name__ == "__main__":
    main()
