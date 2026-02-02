import streamlit as st
from supabase import create_client, Client
import pandas as pd
from datetime import datetime, date, timedelta
from streamlit_gsheets import GSheetsConnection
from langchain_google_genai import ChatGoogleGenerativeAI

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="RBS TaskHub", layout="wide", page_icon="🚀")

# --- MSK STYLE CSS (COMPACT & CLEAN) ---
st.markdown("""
<style>
    /* Reduce main padding */
    .block-container { padding-top: 1rem !important; padding-bottom: 1rem !important; }
    
    /* Compact Text */
    p, .stMarkdown { font-size: 14px !important; margin-bottom: 0px !important; }
    h1, h2, h3 { margin-bottom: 0.5rem !important; margin-top: 0rem !important; }
    
    /* Tighten Expanders (The Task Rows) */
    .streamlit-expanderHeader { 
        padding-top: 5px !important; 
        padding-bottom: 5px !important; 
        background-color: #f0f2f6; 
        border-radius: 5px;
    }
    
    /* Button Styling */
    .stButton button { width: 100%; border-radius: 5px; height: 2.5rem; }
    
    /* Sidebar Compact */
    section[data-testid="stSidebar"] .block-container { padding-top: 2rem; }
</style>
""", unsafe_allow_html=True)

# --- CONFIGURATION ---
COMPANY_DOMAIN = "@rbsgo.com"
ADMIN_EMAIL = "msk@rbsgo.com"
TEAM_MEMBERS = ["msk@rbsgo.com", "praveen@rbsgo.com", "arjun@rbsgo.com", 
                "prasanna@rbsgo.com", "chris@rbsgo.com", "sarah@rbsgo.com"]

# --- SECURE CONNECTION ---
try:
    SUPABASE_URL = st.secrets["connections.supabase"]["SUPABASE_URL"]
    SUPABASE_KEY = st.secrets["connections.supabase"]["SUPABASE_KEY"]
except:
    # Fallback for old secrets format
    try:
        SUPABASE_URL = st.secrets["SUPABASE_URL"]
        SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
    except FileNotFoundError:
        st.error("🚨 Secrets not found!")
        st.stop()

@st.cache_resource
def init_supabase():
    return create_client(SUPABASE_URL, SUPABASE_KEY)

supabase = init_supabase()

# --- GEMINI AI SETUP ---
def get_ai_summary(task_dataframe):
    try:
        if "GOOGLE_API_KEY" in st.secrets:
            api_key = st.secrets["GOOGLE_API_KEY"]
        else:
            return "⚠️ Google API Key missing."
            
        llm = ChatGoogleGenerativeAI(model="gemini-pro", google_api_key=api_key)
        task_text = task_dataframe.to_string(index=False)
        prompt = f"""
        You are an executive assistant. Here is the task list:
        {task_text}
        Provide a 3-bullet executive summary: 
        1. Critical Bottlenecks (Overdue/High Priority)
        2. Today's Focus
        3. A quick motivational one-liner.
        """
        response = llm.invoke(prompt)
        return response.content
    except Exception as e:
        return f"AI Error: {str(e)}"

# --- SYNC & DATA FUNCTIONS ---
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
        # Ensure project_ref is not empty
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

def get_tasks(user_email, is_admin=False):
    query = supabase.table("tasks").select("*")
    if not is_admin:
        query = query.eq("assigned_to", user_email)
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
    else:
        current_user = st.session_state['user']
        is_admin = (current_user == ADMIN_EMAIL)
        
        with st.sidebar:
            st.title("🎛️ Command Ctr")
            st.caption(f"Logged in as: {current_user}")
            nav_mode = st.radio("Navigate", ["📔 My Diary", "➕ New Task", "🔄 Sync Roadmap"])
            st.divider()
            
            # AI SECTION
            st.subheader("✨ AI Insight")
            if st.button("Run Daily Briefing"):
                with st.spinner("Analyzing..."):
                    my_tasks = get_tasks(current_user, is_admin)
                    if not my_tasks.empty:
                        st.info(get_ai_summary(my_tasks))
                    else:
                        st.warning("No data.")
            
            st.divider()
            if st.button("Logout"):
                st.session_state['logged_in'] = False
                st.rerun()

        # --- VIEW: SYNC ---
        if nav_mode == "🔄 Sync Roadmap":
            st.header("🔗 Google Sheets Sync")
            if st.button("🚀 Pull Latest Roadmap", type="primary"):
                with st.spinner("Syncing..."):
                    success, msg = sync_projects()
                    if success: st.success(msg)
                    else: st.error(msg)

        # --- VIEW: NEW TASK ---
        elif nav_mode == "➕ New Task":
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
                    assign_to = st.selectbox("Assign To", TEAM_MEMBERS, index=TEAM_MEMBERS.index(current_user) if current_user in TEAM_MEMBERS else 0)
                with c4:
                    prio = st.selectbox("Priority", ["🔥 High", "⚡ Medium", "🧊 Low"])
                with c5:
                    due = st.date_input("Due Date", value=date.today())
                
                if st.button("Add Task", type="primary", use_container_width=True):
                    if desc:
                        if add_task(current_user, assign_to, desc, prio, due, selected_project):
                            st.toast("✅ Task Created Successfully!")
                    else:
                        st.warning("Description required.")

        # --- VIEW: DIARY (THE MSK DASHBOARD) ---
        elif nav_mode == "📔 My Diary":
            st.title("📔 Operational Diary")
            
            df = get_tasks(current_user, is_admin)
            if not df.empty:
                df['due_date'] = pd.to_datetime(df['due_date'], errors='coerce')
                today_ts = pd.Timestamp.now().normalize()
                active_df = df[df['status'] != 'Completed'].copy()

                # TABS FOR FILTERING (Saves space, looks professional)
                tab1, tab2, tab3, tab4 = st.tabs(["📂 ALL PENDING", "⚡ TODAY", "📅 TOMORROW", "🚨 OVERDUE"])
                
                def render_task_list(filter_type):
                    if filter_type == 'Today': 
                        filtered = active_df[active_df['due_date'] == today_ts]
                    elif filter_type == 'Tomorrow': 
                        filtered = active_df[active_df['due_date'] == today_ts + pd.Timedelta(days=1)]
                    elif filter_type == 'Overdue': 
                        filtered = active_df[active_df['due_date'] < today_ts]
                    else: 
                        filtered = active_df
                    
                    if filtered.empty:
                        st.info("✅ No tasks here. Good job!")
                        return

                    # Sorting: Overdue & High Priority first
                    filtered = filtered.sort_values(by=["due_date", "priority"], ascending=[True, True])
                    
                    # THE MSK COMPACT LIST
                    for index, row in filtered.iterrows():
                        # Create a clean header string
                        d_str = row['due_date'].strftime('%d-%b')
                        proj = row['project_ref'] if row['project_ref'] else "General"
                        priority_icon = "🔴" if "High" in row['priority'] else "🟡" if "Medium" in row['priority'] else "🔵"
                        
                        # THE EXPANDER: This makes it compact!
                        # Header shows the Summary. Click to see details.
                        with st.expander(f"{priority_icon}  **{d_str}** | {row['task_desc']}  _({proj})_"):
                            c1, c2 = st.columns([3, 1])
                            with c1:
                                st.caption(f"Assigned by: {row['created_by']}")
                                if row['staff_remarks']: st.info(f"Last Remark: {row['staff_remarks']}")
                                # UNIQUE KEY FIX: Added filter_type to the key
                                new_rem = st.text_input("Update Remark", key=f"r_{row['id']}_{filter_type}")
                            with c2:
                                st.write("") # Spacer
                                st.write("")
                                # UNIQUE KEY FIX: Added filter_type to the key
                                if st.button("Mark Done", key=f"d_{row['id']}_{filter_type}", type="primary", use_container_width=True):
                                    remark_to_save = new_rem if new_rem else row['staff_remarks']
                                    update_task_status(row['id'], "Completed", remark_to_save)
                                    st.rerun()

                with tab1: render_task_list('All')
                with tab2: render_task_list('Today')
                with tab3: render_task_list('Tomorrow')
                with tab4: render_task_list('Overdue')

            else:
                st.info("👋 Welcome! You have no tasks. Go to 'New Task' to create one.")

if __name__ == "__main__":
    main()
