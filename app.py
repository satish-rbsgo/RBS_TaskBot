import streamlit as st
from supabase import create_client, Client
import pandas as pd
from datetime import datetime, date, timedelta
from streamlit_gsheets import GSheetsConnection
from langchain_google_genai import ChatGoogleGenerativeAI
from streamlit_option_menu import option_menu

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

# --- 1. ACCESS CONTROL LISTS (The Master Logic) ---
# Managers: Can Sync, View All Diaries, Assign to Anyone
MANAGERS = ["satish.m@rbsgo.com", "sriram@rbsgo.com", "msk@rbsgo.com"] 

# All Authorized Users: Can Login
TEAM_MEMBERS = [
    "satish.m@rbsgo.com", "sriram@rbsgo.com", "msk@rbsgo.com",
    "praveen@rbsgo.com", "arjun@rbsgo.com", "prasanna@rbsgo.com", 
    "chris@rbsgo.com", "sarah@rbsgo.com"
]
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

# --- DATA FUNCTIONS ---
def sync_projects():
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        df = conn.read(worksheet="ROADMAP") 
        count = 0
        for index, row in df.iterrows():
            data = {
                "name": row['Interface Name'],
                "status": row['Stage'],
                "target_date": str(row['Target Date']),
                "description": row['Description'],
                "client": row['Client']
            }
            supabase.table("projects").upsert(data, on_conflict="name").execute()
            count += 1
        return True, f"Synced {count} Projects!"
    except Exception as e:
        return False, f"Sync Error: {str(e)}"

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
    # Logic: If target_email is None, return ALL tasks (for Managers view all)
    # If target_email is set, filter by that user
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

    # --- LOGIN SCREEN ---
    if not st.session_state['logged_in']:
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            st.title("🚀 RBS TaskHub")
            with st.container(border=True):
                email_input = st.text_input("Enter Work Email:")
                if st.button("Login", use_container_width=True):
                    email = email_input.lower().strip()
                    # 1. Check Domain
                    if email.endswith(COMPANY_DOMAIN):
                        # 2. Check Access List
                        if email in TEAM_MEMBERS:
                            st.session_state['logged_in'] = True
                            st.session_state['user'] = email
                            st.rerun()
                        else:
                            st.error("🚫 Access Denied. You are not in the Team List.")
                    else:
                        st.error(f"🚫 Restricted Access. {COMPANY_DOMAIN} only.")
    
    # --- DASHBOARD ---
    else:
        current_user = st.session_state['user']
        # DETERMINE ROLE
        is_manager = current_user in MANAGERS
        
        # --- SIDEBAR ---
        with st.sidebar:
            st.markdown(f"### 💼 RBS Workspace")
            role_label = "Manager" if is_manager else "Team Member"
            st.caption(f"{current_user.split('@')[0].title()} ({role_label})")
            
            # DYNAMIC MENU: Hide 'Sync' for non-managers
            menu_options = ["My Diary", "New Task"]
            menu_icons = ["journal-bookmark", "plus-circle"]
            
            if is_manager:
                menu_options.append("Sync Roadmap")
                menu_icons.append("cloud-arrow-down")

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
            
            # AI Briefing
            st.markdown("**🤖 Assistant**")
            if st.button("Generate Briefing", use_container_width=True):
                with st.spinner("Analyzing..."):
                    # Managers analyze ALL data, Members analyze OWN data
                    tasks_to_analyze = get_tasks(None) if is_manager else get_tasks(current_user)
                    if not tasks_to_analyze.empty:
                        st.info(get_ai_summary(tasks_to_analyze))
                    else:
                        st.warning("No data.")
            
            st.write("") 
            if st.button("Logout", use_container_width=True):
                st.session_state['logged_in'] = False
                st.rerun()

        # --- VIEW: SYNC (Managers Only) ---
        if nav_mode == "Sync Roadmap" and is_manager:
            st.header("🔗 Google Sheets Sync")
            st.info("Update your Google Sheet 'ROADMAP' tab, then click below.")
            if st.button("🚀 Pull Latest Roadmap", type="primary"):
                with st.spinner("Syncing..."):
                    success, msg = sync_projects()
                    if success: st.success(msg)
                    else: st.error(msg)

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
                    # MANAGER LOGIC: Dropdown has everyone. TEAM LOGIC: Locked to self.
                    if is_manager:
                        assign_to = st.selectbox("Assign To", TEAM_MEMBERS, index=TEAM_MEMBERS.index(current_user) if current_user in TEAM_MEMBERS else 0)
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
            
            # 1. FETCH DATA BASED ON ROLE
            df = pd.DataFrame()
            
            if is_manager:
                # Manager Layout: Filter Bar + Title
                c_filter, c_title = st.columns([1, 3])
                with c_filter:
                    view_target = st.selectbox("View Diary For:", ["All Users"] + TEAM_MEMBERS)
                with c_title:
                    st.title("📔 Operational Diary")
                
                # Fetch Logic
                if view_target == "All Users":
                    df = get_tasks(None) # Get All
                else:
                    df = get_tasks(view_target) # Get Specific User
            else:
                # Team Layout: Simple Title
                st.title("📔 My Diary")
                df = get_tasks(current_user) # Only Self
            
            # 2. RENDER THE LIST (Common Logic)
            if not df.empty:
                df['due_date'] = pd.to_datetime(df['due_date'], errors='coerce')
                today_ts = pd.Timestamp.now().normalize()
                active_df = df[df['status'] != 'Completed'].copy()

                # CALCULATE COUNTS (The Fancy Badges)
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

                # Filter Logic based on Menu Selection
                if opt_today in selected_filter: 
                    filtered = active_df[active_df['due_date'] == today_ts]
                elif opt_tmrw in selected_filter: 
                    filtered = active_df[active_df['due_date'] == today_ts + pd.Timedelta(days=1)]
                elif opt_over in selected_filter: 
                    filtered = active_df[active_df['due_date'] < today_ts]
                else: 
                    filtered = active_df
                
                st.write("") 

                if filtered.empty:
                    st.info(f"✅ No tasks found for this category.")
                else:
                    filtered = filtered.sort_values(by=["due_date", "priority"], ascending=[True, True])
                    for index, row in filtered.iterrows():
                        d_str = row['due_date'].strftime('%d-%b')
                        proj = row['project_ref'] if row['project_ref'] else "General"
                        priority_icon = "🔴" if "High" in row['priority'] else "🟡" if "Medium" in row['priority'] else "🔵"
                        
                        # If Manager viewing "All", show who owns the task
                        assign_label = ""
                        if is_manager and 'assigned_to' in row:
                             name = row['assigned_to'].split('@')[0].title()
                             assign_label = f" ➝ 👤 {name}"

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
