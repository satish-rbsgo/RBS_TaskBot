import streamlit as st
from supabase import create_client, Client
import pandas as pd
import re
from datetime import datetime, date

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="RBS TaskHub", layout="wide", page_icon="🚀")

# --- CONFIGURATION ---
COMPANY_DOMAIN = "@rbsgo.com"
ADMIN_EMAIL = "msk@rbsgo.com"

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

try:
    supabase = init_supabase()
except Exception as e:
    st.error(f"Failed to connect to Database: {e}")
    st.stop()

# --- DATABASE FUNCTIONS ---
def add_task_to_db(created_by, assigned_to, task_desc, priority, due_date):
    try:
        data = {
            "created_by": created_by,
            "assigned_to": assigned_to,
            "task_desc": task_desc,
            "status": "Open",
            "priority": priority,
            "due_date": str(due_date) if due_date else None,
            "staff_remarks": "",
            "manager_remarks": ""
        }
        supabase.table("tasks").insert(data).execute()
        return True
    except Exception as e:
        st.error(f"Error saving task: {e}")
        return False

def get_tasks(user_email, is_admin=False):
    try:
        query = supabase.table("tasks").select("*")
        if not is_admin:
            query = query.eq("assigned_to", user_email)
        
        # Filter out completed tasks (optional - usually better to see history)
        # query = query.neq("status", "Completed") 
        
        response = query.order("id", desc=True).execute()
            
        if response.data:
            return pd.DataFrame(response.data)
        else:
            return pd.DataFrame()
    except Exception as e:
        st.error(f"Database Error: {e}")
        return pd.DataFrame()

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
        st.error(f"Update failed: {e}")
        return False

# --- PARSING ENGINE ---
def parse_command(command_text, current_user):
    assigned_to = current_user 
    task_detail = command_text
    
    # Team Mapping (Add your team members here)
    team_map = {
        "praveen": "praveen@rbsgo.com",
        "arjun": "arjun@rbsgo.com",
        "msk": "msk@rbsgo.com",
        "prasanna": "prasanna@rbsgo.com",
        "chris": "chris@rbsgo.com"
    }
    
    lower_cmd = command_text.lower()
    for name, email in team_map.items():
        if name in lower_cmd:
            assigned_to = email
            task_detail = re.sub(name, "", task_detail, flags=re.IGNORECASE)
            task_detail = re.sub(r"^(ask|tell|assign|to|request)\s+", "", task_detail, flags=re.IGNORECASE).strip()
            break
            
    return assigned_to, task_detail

# --- MAIN APP ---
def main():
    if 'logged_in' not in st.session_state:
        st.session_state['logged_in'] = False

    # --- LOGIN SCREEN ---
    if not st.session_state['logged_in']:
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            st.title("🚀 RBS TaskHub")
            st.markdown("### Secure Internal Workspace")
            with st.container(border=True):
                email = st.text_input("Work Email Address")
                if st.button("Access Dashboard", type="primary", use_container_width=True):
                    if email.endswith(COMPANY_DOMAIN):
                        st.session_state['logged_in'] = True
                        st.session_state['user'] = email
                        st.rerun()
                    else:
                        st.error(f"🚫 Access Denied. {COMPANY_DOMAIN} only.")

    # --- MAIN DASHBOARD ---
    else:
        current_user = st.session_state['user']
        is_admin = (current_user == ADMIN_EMAIL)
        
        # Sidebar
        with st.sidebar:
            st.image("https://cdn-icons-png.flaticon.com/512/3135/3135715.png", width=50)
            st.title(f"Hi, {current_user.split('@')[0].title()}")
            st.caption(current_user)
            if is_admin:
                st.warning("⚡ HEAD MODE ACTIVE")
            st.divider()
            if st.button("Logout", use_container_width=True):
                st.session_state['logged_in'] = False
                st.rerun()

        # Header Metrics
        st.title("Task Command Center")
        
        # 1. NEW TASK CREATION (Beautiful Expander)
        with st.expander("➕ Create New Task", expanded=True):
            c1, c2, c3, c4 = st.columns([3, 1, 1, 1])
            with c1:
                cmd = st.text_input("Task Description (or Chat Command)", placeholder="e.g. Ask Praveen to update the API")
            with c2:
                priority = st.selectbox("Priority", ["🔥 High", "⚡ Medium", "🧊 Low"], index=1)
            with c3:
                due_date = st.date_input("Due Date", min_value=date.today())
            with c4:
                st.write("") # Spacer
                st.write("") 
                if st.button("Assign", type="primary", use_container_width=True):
                    if cmd:
                        who, what = parse_command(cmd, current_user)
                        if add_task_to_db(current_user, who, what, priority, due_date):
                            st.toast(f"✅ Assigned to {who}", icon="🚀")
                            st.rerun()

        st.divider()

        # 2. DATA LOADING & PROCESSING
        df = get_tasks(current_user, is_admin)

        if df.empty:
            st.info("🎉 You have no pending tasks. Enjoy your day!")
        else:
            # Metrics Row
            m1, m2, m3 = st.columns(3)
            m1.metric("Total Tasks", len(df))
            m2.metric("High Priority", len(df[df['priority'] == '🔥 High']))
            m3.metric("Completed", len(df[df['status'] == 'Completed']))

            # 3. INTERACTIVE DATA EDITOR (The World Class Part)
            st.subheader("📋 Active Task Board")
            
            # This turns the dataframe into an interactive, colorful table
            edited_df = st.data_editor(
                df,
                column_config={
                    "id": st.column_config.NumberColumn("ID", disabled=True, width="small"),
                    "task_desc": st.column_config.TextColumn("Task Description", disabled=True, width="large"),
                    "assigned_to": st.column_config.TextColumn("Owner", disabled=True, width="medium"),
                    "priority": st.column_config.SelectboxColumn(
                        "Priority",
                        options=["🔥 High", "⚡ Medium", "🧊 Low"],
                        width="medium",
                        required=True,
                    ),
                    "status": st.column_config.SelectboxColumn(
                        "Status",
                        options=["Open", "In Progress", "Pending Info", "Completed"],
                        width="medium",
                        required=True,
                    ),
                    "due_date": st.column_config.DateColumn("Due Date", format="DD MMM YYYY"),
                    "staff_remarks": st.column_config.TextColumn("Staff Remarks"),
                    "manager_remarks": st.column_config.TextColumn("Manager Feedback"),
                    "created_at": None, # Hide these columns
                    "created_by": None
                },
                disabled=["id", "created_by", "assigned_to", "task_desc", "priority", "due_date"], # Only allow editing Status/Remarks for safety
                hide_index=True,
                use_container_width=True,
                key="task_editor"
            )

            # 4. SAVE CHANGES BUTTON
            # (Streamlit data editor allows bulk edits, but we need a button to push changes to DB)
            # For this version, we stick to the reliable Card View for editing to prevent sync errors.
            
            st.caption("👇 Edit Status & Remarks below")
            
            # SORT: High priority first, then new tasks
            df = df.sort_values(by=["id"], ascending=False)

            for index, row in df.iterrows():
                # Color code the card border based on Priority
                border_color = "red" if "High" in row['priority'] else "grey"
                
                with st.container(border=True):
                    col_a, col_b, col_c, col_d = st.columns([3, 2, 2, 1])
                    
                    with col_a:
                        st.markdown(f"**{row['task_desc']}**")
                        st.caption(f"👤 **{row['assigned_to']}** | 📅 Due: {row['due_date']} | {row['priority']}")
                    
                    with col_b:
                        curr_rem = row['staff_remarks'] if row['staff_remarks'] else ""
                        new_rem = st.text_input("My Update", value=curr_rem, key=f"rem_{row['id']}", placeholder="Type status update...")
                    
                    with col_c:
                        mgr_rem = row['manager_remarks'] if row['manager_remarks'] else ""
                        # Only Admin can edit manager remarks
                        new_mgr = st.text_input("Feedback", value=mgr_rem, key=f"mgr_{row['id']}", disabled=not is_admin, placeholder="Head's feedback...")
                    
                    with col_d:
                        # Status with Colors
                        status_options = ["Open", "In Progress", "Pending Info", "Completed"]
                        try:
                            s_idx = status_options.index(row['status'])
                        except:
                            s_idx = 0
                        new_stat = st.selectbox("Status", status_options, index=s_idx, key=f"stat_{row['id']}", label_visibility="collapsed")
                        
                        if st.button("Update", key=f"save_{row['id']}", type="secondary"):
                            update_task(row['id'], new_stat, new_rem, new_mgr)
                            st.rerun()

if __name__ == "__main__":
    main()
