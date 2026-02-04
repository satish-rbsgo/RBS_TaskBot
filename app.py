import streamlit as st
from supabase import create_client, Client
import pandas as pd
from datetime import datetime, date, timedelta
from streamlit_gsheets import GSheetsConnection
from langchain_google_genai import ChatGoogleGenerativeAI
from streamlit_option_menu import option_menu
import time

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="RBS TaskHub", layout="wide", page_icon="🚀")

# --- MSK STYLE CSS ---
st.markdown("""
<style>
    .block-container { padding-top: 1rem !important; padding-bottom: 1rem !important; }
    p, .stMarkdown { font-size: 14px !important; margin-bottom: 0px !important; }
    h1, h2, h3 { margin-bottom: 0.5rem !important; margin-top: 0rem !important; }
    .streamlit-expanderHeader { 
        padding-top: 5px !important; padding-bottom: 5px !important; 
        background-color: #f0f2f6; border-radius: 5px;
    }
    .stButton button { width: 100%; border-radius: 5px; height: 2.5rem; }
    section[data-testid="stSidebar"] .block-container { padding-top: 2rem; }
</style>
""", unsafe_allow_html=True)

# --- CONFIGURATION ---
COMPANY_DOMAIN = "@rbsgo.com"

# --- SECURE CONNECTION ---
try:
    SUPABASE_URL = st.secrets["connections.supabase"]["SUPABASE_URL"]
    SUPABASE_KEY = st.secrets["connections.supabase"]["SUPABASE_KEY"]
except:
    try:
        SUPABASE_URL = st.secrets["SUPABASE_URL"]
        SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
    except:
        st.error("🚨 Secrets not found!")
        st.stop()

@st.cache_resource
def init_supabase():
    return create_client(SUPABASE_URL, SUPABASE_KEY)

supabase = init_supabase()

# --- AUTHENTICATION & MASTERS (DB DRIVEN) ---
def verify_user_in_db(email):
    """Check user_master table for access"""
    try:
        response = supabase.table("user_master").select("*").eq("email", email).eq("status", "active").execute()
        if response.data:
            return response.data[0]
        return None
    except Exception as e:
        return None

def get_active_users():
    """Fetch all active users for dropdowns (Managers only)"""
    try:
        response = supabase.table("user_master").select("email").eq("status", "active").execute()
        return [u['email'] for u in response.data] if response.data else []
    except:
        return []

def create_new_user(email, name, role):
    """Add a new user to the master table"""
    try:
        exists = supabase.table("user_master").select("*").eq("email", email).execute()
        if exists.data: return False, "User already exists!"
        
        data = {"email": email, "name": name, "role": role, "status": "active"}
        supabase.table("user_master").insert(data).execute()
        return True, "User added successfully!"
    except Exception as e:
        return False, str(e)

def toggle_user_status(email, current_status):
    """Deactivate or Reactivate a user"""
    try:
        new_status = "inactive" if current_status == "active" else "active"
        supabase.table("user_master").update({"status": new_status}).eq("email", email).execute()
        return True
    except:
        return False

# --- GEMINI AI ---
def get_ai_summary(task_dataframe):
    try:
        if "GOOGLE_API_KEY" in st.secrets:
            api_key = st.secrets["GOOGLE_API_KEY"]
        else:
            return "⚠️ Google API Key missing."
        llm = ChatGoogleGenerativeAI(model="gemini-pro", google_api_key=api_key)
        task_text = task_dataframe.to_string(index=False)
        prompt = f"""
        Act as a Project Manager. Summarize this task list in 3 bullet points:
        1. Critical Bottlenecks (Overdue/High Priority)
        2. Today's Focus
        3. Motivational one-liner.
        Tasks: {task_text}
        """
        response = llm.invoke(prompt)
        return response.content
    except Exception as e:
        return f"AI Error: {str(e)}"

# --- DATA FUNCTIONS (CRASH PROOF SYNC) ---
def sync_projects():
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        df = conn.read(worksheet="ROADMAP") 
        count = 0
        
        # 1. Validation: Check if sheet is empty
        if df.empty:
            return False, "⚠️ Google Sheet is empty or tab 'ROADMAP' not found."

        # 2. Iterate
        for index, row in df.iterrows():
            # Check for empty Interface Name
            if pd.isna(row.get('Interface Name')) or str(row.get('Interface Name')).strip() == '':
                continue
            
            # 3. CRITICAL: Clean Data (Convert NaN to empty strings to prevent HTTP 400)
            def clean_val(val):
                if pd.isna(val): return ""
                return str(val).strip()

            p_name = clean_val(row.get('Interface Name'))
            p_status = clean_val(row.get('Status'))
            p_desc = clean_val(row.get('Particulars')) # Maps 'Particulars' -> 'description'
            p_vendor = clean_val(row.get('Vendor'))    # Maps 'Vendor' -> 'vendor'

            data = {
                "name": p_name,
                "status": p_status,
                "description": p_desc,
                "vendor": p_vendor
            }
            
            # 4. Safe Upsert
            try:
                supabase.table("projects").upsert(data, on_conflict="name").execute()
                count += 1
            except Exception as row_error:
                # If a specific row fails, log it but continue syncing others
                print(f"Skipped row {p_name}: {row_error}")
                continue
            
        get_projects.clear() # Clear cache
        return True, f"✅ Successfully Synced {count} Projects!"
        
    except Exception as e:
        return False, f"❌ Sync Failed. Detail: {str(e)}"

@st.cache_data(ttl=60)
def get_projects():
    try:
        response = supabase.table("projects").select("name").execute()
        return [row['name'] for row in response.data] if response.data else []
    except:
        return []

def add_task(created_by, assigned_to, task_desc, priority, due_date, project_ref):
    try:
        final_date = str(due_date) if due_date else str(date.today())
        final_project = project_ref if project_ref else "General"
        data = {
            "created_by": created_by,
            "assigned_to": assigned_to,
            "task_desc": task_desc,
            "status": "Open",
            "priority": priority,
            "due_date": final_date,
            "project_ref": final_project,
            "staff_remarks": "",
            "manager_remarks": ""
        }
        supabase.table("tasks").insert(data).execute()
        return True
    except Exception as e:
        st.error(f"Error: {e}")
        return False

def get_tasks(target_email=None):
    query = supabase.table("tasks").select("*")
    if target_email:
        query = query.eq("assigned_to", target_email)
    response = query.execute()
    return pd.DataFrame(response.data) if response.data else pd.DataFrame()

def update_task_status(task_id, new_status, remarks=None):
    try:
        data = {"status": new_status}
        if remarks: data["staff_remarks"] = remarks
        supabase.table("tasks").update(data).eq("id", task_id).execute()
        return True
    except:
        return False

# --- MAIN APP ---
def main():
    if 'logged_in' not in st.session_state: st.session_state['logged_in'] = False
    if 'user_role' not in st.session_state: st.session_state['user_role'] = None
    if 'user_name' not in st.session_state: st.session_state['user_name'] = None

    # --- LOGIN SCREEN ---
    if not st.session_state['logged_in']:
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            st.title("🚀 RBS TaskHub")
            with st.container(border=True):
                email_input = st.text_input("Enter Work Email:")
                if st.button("Login", use_container_width=True):
                    email = email_input.lower().strip()
                    if email.endswith(COMPANY_DOMAIN):
                        user_record = verify_user_in_db(email)
                        if user_record:
                            st.session_state['logged_in'] = True
                            st.session_state['user'] = user_record['email']
                            st.session_state['user_role'] = user_record['role'] 
                            st.session_state['user_name'] = user_record['name']
                            st.rerun()
                        else:
                            st.error("🚫 Access Denied. Contact Admin (Satish/Sriram).")
                    else:
                        st.error(f"🚫 Restricted Access. {COMPANY_DOMAIN} only.")
    
    # --- DASHBOARD ---
    else:
        current_user = st.session_state['user']
        user_role = st.session_state['user_role']
        user_name = st.session_state['user_name']
        is_manager = (user_role == 'manager')
        
        with st.sidebar:
            st.markdown(f"### 💼 RBS Workspace")
            role_label = "Manager" if is_manager else "Team Member"
            st.caption(f"{user_name} ({role_label})")
            
            # DYNAMIC MENU
            menu_options = ["My Diary", "New Task"]
            menu_icons = ["journal-bookmark", "plus-circle"]
            
            if is_manager:
                menu_options.append("Sync Roadmap")
                menu_icons.append("cloud-arrow-down")
                menu_options.append("Team Master") 
                menu_icons.append("people-fill")

            nav_mode = option_menu(
                menu_title=None, 
                options=menu_options, 
                icons=menu_icons, 
                menu_icon="cast", 
                default_index=0,
                styles={
                    "container": {"padding": "0!important", "background-color": "#fafafa"},
                    "icon": {"color": "black", "font-size": "16px"}, 
                    "nav-link": {"font-size": "14px", "text-align": "left", "margin":"0px"},
                    "nav-link-selected": {"background-color": "#ff4b4b"},
                }
            )
            
            st.divider()
            st.markdown("**🤖 Assistant**")
            if st.button("Generate Briefing", use_container_width=True):
                with st.spinner("Analyzing..."):
                    tasks_to_analyze = get_tasks(None) if is_manager else get_tasks(current_user)
                    if not tasks_to_analyze.empty:
                        st.info(get_ai_summary(tasks_to_analyze))
                    else:
                        st.warning("No data.")
            
            st.write("") 
            if st.button("Logout", use_container_width=True):
                st.session_state['logged_in'] = False
                st.session_state['user_role'] = None
                st.rerun()

        # --- VIEW: SYNC ---
        if nav_mode == "Sync Roadmap" and is_manager:
            st.header("🔗 Google Sheets Sync")
            st.info("Update your Google Sheet 'ROADMAP' tab, then click below.")
            if st.button("🚀 Pull Latest Roadmap", type="primary"):
                with st.spinner("Syncing..."):
                    success, msg = sync_projects()
                    if success: st.success(msg)
                    else: st.error(msg)

        # --- VIEW: TEAM MASTER ---
        elif nav_mode == "Team Master" and is_manager:
            st.title("👥 Team Master")
            with st.expander("➕ Add New User", expanded=True):
                with st.form("add_user", clear_on_submit=True):
                    c1, c2, c3 = st.columns(3)
                    new_name = c1.text_input("Name")
                    new_email = c2.text_input("Email (must be @rbsgo.com)")
                    new_role = c3.selectbox("Role", ["member", "manager"])
                    
                    if st.form_submit_button("Add User", type="primary"):
                        if new_email.endswith("@rbsgo.com") and new_name:
                            success, msg = create_new_user(new_email.lower().strip(), new_name, new_role)
                            if success: 
                                st.toast(msg, icon="✅")
                                time.sleep(1)
                                st.rerun()
                            else: st.error(msg)
                        else:
                            st.warning("Invalid Email or Name.")

            st.divider()
            st.subheader("Current Team List")
            users = supabase.table("user_master").select("*").order("name").execute().data
            if users:
                df_users = pd.DataFrame(users)
                for i, u in df_users.iterrows():
                    with st.container(border=True):
                        c1, c2, c3, c4 = st.columns([2, 3, 1, 1])
                        c1.write(f"**{u['name']}**")
                        c2.write(f"`{u['email']}`")
                        c3.caption(f"_{u['role']}_")
                        btn_label = "🔴 Deactivate" if u['status'] == 'active' else "🟢 Activate"
                        if c4.button(btn_label, key=f"tog_{u['email']}"):
                            toggle_user_status(u['email'], u['status'])
                            st.rerun()
            else:
                st.info("No users found.")

        # --- VIEW: NEW TASK ---
        elif nav_mode == "New Task":
            st.header("✨ Create New Task")
            with st.container(border=True):
                c1, c2 = st.columns([2, 1])
                with c1:
                    desc = st.text_input("Task Description", placeholder="What needs to be done?")
                with c2:
                    project_list = get_projects()
                    selected_project = st.selectbox("Project", ["General"] + project_list)

                c3, c4, c5 = st.columns(3)
                with c3:
                    if is_manager:
                        all_active_users = get_active_users()
                        assign_to = st.selectbox("Assign To", all_active_users, index=all_active_users.index(current_user) if current_user in all_active_users else 0)
                    else:
                        assign_to = st.selectbox("Assign To", [current_user], disabled=True)
                
                with c4:
                    prio = st.selectbox("Priority", ["🔥 High", "⚡ Medium", "🧊 Low"])
                with c5:
                    due = st.date_input("Due Date", value=date.today())
                
                if st.button("Add Task", type="primary", use_container_width=True):
                    if desc:
                        if add_task(current_user, assign_to, desc, prio, due, selected_project):
                            st.toast(f"✅ Task assigned to {assign_to}!")
                    else:
                        st.warning("Description required.")

        # --- VIEW: DIARY ---
        elif nav_mode == "My Diary":
            df = pd.DataFrame()
            if is_manager:
                c_filter, c_title = st.columns([1, 3])
                with c_filter:
                    all_active_users = get_active_users()
                    view_target = st.selectbox("View Diary For:", ["All Users"] + all_active_users)
                with c_title:
                    st.title("📔 Operational Diary")
                
                if view_target == "All Users":
                    df = get_tasks(None) 
                else:
                    df = get_tasks(view_target) 
            else:
                st.title("📔 My Diary")
                df = get_tasks(current_user) 
            
            if not df.empty:
                df['due_date'] = pd.to_datetime(df['due_date'], errors='coerce')
                today_ts = pd.Timestamp.now().normalize()
                active_df = df[df['status'] != 'Completed'].copy()

                c_all = len(active_df)
                c_today = len(active_df[active_df['due_date'] == today_ts])
                c_tmrw = len(active_df[active_df['due_date'] == today_ts + pd.Timedelta(days=1)])
                c_over = len(active_df[active_df['due_date'] < today_ts])

                opt_all = f"All Pending ({c_all})"
                opt_today = f"Today ({c_today})"
                opt_tmrw = f"Tomorrow ({c_tmrw})"
                opt_over = f"Overdue ({c_over})"

                selected_filter = option_menu(
                    menu_title=None,
                    options=[opt_all, opt_today, opt_tmrw, opt_over],
                    icons=["folder", "lightning", "calendar", "exclamation-triangle"],
                    orientation="horizontal",
                    styles={"container": {"padding": "0!important", "background-color": "#fafafa"}}
                )

                if selected_filter == opt_today: 
                    filtered = active_df[active_df['due_date'] == today_ts]
                elif selected_filter == opt_tmrw: 
                    filtered = active_df[active_df['due_date'] == today_ts + pd.Timedelta(days=1)]
                elif selected_filter == opt_over: 
                    filtered = active_df[active_df['due_date'] < today_ts]
                else: 
                    filtered = active_df
                
                st.write("") 

                if filtered.empty:
                    st.info(f"✅ No tasks found for '{selected_filter}'.")
                else:
                    filtered = filtered.sort_values(by=["due_date", "priority"], ascending=[True, True])
                    for index, row in filtered.iterrows():
                        d_str = row['due_date'].strftime('%d-%b')
                        proj = row.get('project_ref', 'General') 
                        if not proj: proj = "General"
                        priority_icon = "🔴" if "High" in row['priority'] else "🟡" if "Medium" in row['priority'] else "🔵"
                        assign_label = f" ➝ {row['assigned_to'].split('@')[0].title()}" if (is_manager and 'assigned_to' in row) else ""

                        with st.expander(f"{priority_icon}  **{d_str}** | {row['task_desc']} _({proj}){assign_label}_"):
                            c1, c2 = st.columns([3, 1])
                            with c1:
                                st.caption(f"Created by: {row['created_by']}")
                                if row['staff_remarks']: st.info(f"Remark: {row['staff_remarks']}")
                                new_rem = st.text_input("Update", key=f"r_{row['id']}_{selected_filter}")
                            with c2:
                                st.write("")
                                st.write("") 
                                if st.button("Mark Done", key=f"d_{row['id']}_{selected_filter}", type="primary"):
                                    remark_to_save = new_rem if new_rem else row['staff_remarks']
                                    update_task_status(row['id'], "Completed", remark_to_save)
                                    st.rerun()
            else:
                st.info("👋 No active tasks found.")

if __name__ == "__main__":
    main()
