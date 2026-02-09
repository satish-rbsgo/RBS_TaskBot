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
    
    /* Make the New Task Expander look like a big Action Button */
    .streamlit-expanderHeader { 
        padding-top: 8px !important; padding-bottom: 8px !important; 
        background-color: #f0f2f6; border-radius: 8px; font-weight: bold;
        border: 1px solid #e0e0e0;
    }
    
    .stButton button { width: 100%; border-radius: 5px; height: 2.5rem; }
    section[data-testid="stSidebar"] .block-container { padding-top: 2rem; }
    
    /* Custom Scrollbar for the Task Container */
    div[data-testid="stVerticalBlock"] > div[style*="overflow"]::-webkit-scrollbar {
        width: 8px;
    }
    div[data-testid="stVerticalBlock"] > div[style*="overflow"]::-webkit-scrollbar-thumb {
        background-color: #ccc;
        border-radius: 4px;
    }
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

# --- AUTHENTICATION & MASTERS ---
def verify_user_in_db(email):
    try:
        response = supabase.table("user_master").select("*").eq("email", email).eq("status", "active").execute()
        if response.data: return response.data[0]
        return None
    except: return None

def get_active_users():
    try:
        response = supabase.table("user_master").select("email").eq("status", "active").execute()
        return [u['email'] for u in response.data] if response.data else []
    except: return []

def create_new_user(email, name, role):
    try:
        exists = supabase.table("user_master").select("*").eq("email", email).execute()
        if exists.data: return False, "User already exists!"
        data = {"email": email, "name": name, "role": role, "status": "active"}
        supabase.table("user_master").insert(data).execute()
        return True, "User added successfully!"
    except Exception as e: return False, str(e)

def toggle_user_status(email, current_status):
    try:
        new_status = "inactive" if current_status == "active" else "active"
        supabase.table("user_master").update({"status": new_status}).eq("email", email).execute()
        return True
    except: return False

# --- GEMINI AI ---
def get_ai_summary(task_dataframe):
    try:
        if "GOOGLE_API_KEY" in st.secrets:
            api_key = st.secrets["GOOGLE_API_KEY"]
        else: return "⚠️ Google API Key missing."
        llm = ChatGoogleGenerativeAI(model="gemini-pro", google_api_key=api_key)
        task_text = task_dataframe.to_string(index=False)
        prompt = f"Act as Project Manager. Summarize:\n1. Critical Bottlenecks\n2. Focus\n3. Motivation\nTasks: {task_text}"
        response = llm.invoke(prompt)
        return response.content
    except Exception as e: return f"AI Error: {str(e)}"

# --- SYNC LOGIC ---
def sync_projects():
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        df = conn.read(worksheet="ROADMAP", ttl=0) 
        if df.empty: return False, "⚠️ Sheet is empty or missing 'ROADMAP' tab."

        df = df.fillna("").astype(str)
        count = 0
        for index, row in df.iterrows():
            if row.get('Interface Name', '').strip() == '': continue
            
            p_name = row.get('Interface Name', '').strip()
            p_status = row.get('Status', '').strip()
            p_desc = row.get('Particulars', '').strip()
            p_vendor = row.get('Vendor', '').strip()

            data = {
                "name": p_name,
                "status": p_status,
                "description": p_desc,
                "vendor": p_vendor
            }
            try:
                supabase.table("projects").upsert(data, on_conflict="name").execute()
                count += 1
            except Exception as row_error:
                print(f"Row skipped {p_name}: {row_error}")
                continue
            
        get_projects_master.clear() # Clear cache to refresh
        return True, f"✅ Synced {count} Projects!"
    except Exception as e:
        return False, f"❌ Sync Error: {str(e)}"

# --- OPTIMIZED DATA LOADING (THE SPEED FIX) ---
@st.cache_data(ttl=300) # Cache project list for 5 mins
def get_projects_master():
    try:
        response = supabase.table("projects").select("name").execute()
        return [row['name'] for row in response.data] if response.data else []
    except: return []

def load_data_efficiently(target_email=None):
    """
    Fetches Tasks AND calculates Unique lists in ONE go.
    Handles Data Cleaning for Dates to prevent crashes.
    """
    # 1. Fetch Tasks (Sorted by Date in DB for speed)
    query = supabase.table("tasks").select("*").order("due_date", desc=False)
    if target_email: query = query.eq("assigned_to", target_email)
    
    response = query.execute()
    df = pd.DataFrame(response.data) if response.data else pd.DataFrame()

    # --- CRITICAL FIX: DATE HANDLING ---
    if not df.empty:
        # Force conversion to datetime, turning errors into NaT (Not a Time)
        df['due_date'] = pd.to_datetime(df['due_date'], errors='coerce')
        # Fill missing dates with Today to prevent 'NaTType' errors later
        df['due_date'] = df['due_date'].fillna(pd.Timestamp.now().normalize())

        # 2. Extract Unique Values from memory
        used_coords = df['coordinator'].dropna().unique().tolist()
        used_projs = df['project_ref'].dropna().unique().tolist()
    else:
        used_coords = []
        used_projs = []

    # 3. Get Master Projects (Cached)
    master_projs = get_projects_master()
    
    # 4. Merge lists
    all_projects = sorted(list(set(master_projs + used_projs + ["General"])))
    base_coords = ["Sales Team", "Client", "Support Team", "Internal", "Management"]
    all_coords = sorted(list(set(base_coords + used_coords)))

    return df, all_projects, all_coords

# --- TASK FUNCTIONS ---
def add_task(created_by, assigned_to, task_desc, priority, due_date, project_ref, coordinator, email_subject, points):
    try:
        final_date = str(due_date) if due_date else str(date.today())
        final_project = project_ref if project_ref and project_ref.strip() != "" else "General"
        final_coord = coordinator if coordinator and coordinator.strip() != "" else "General"
        
        data = {
            "created_by": created_by, 
            "assigned_to": assigned_to, 
            "task_desc": task_desc,
            "status": "Open", 
            "priority": priority, 
            "due_date": final_date,
            "project_ref": final_project, 
            "staff_remarks": "", 
            "manager_remarks": "",
            "coordinator": final_coord,
            "email_subject": email_subject,
            "points": points
        }
        supabase.table("tasks").insert(data).execute()
        return True
    except Exception as e:
        st.error(f"Add Task Error: {e}")
        return False

def get_tasks(target_email=None):
    query = supabase.table("tasks").select("*")
    if target_email: query = query.eq("assigned_to", target_email)
    response = query.execute()
    return pd.DataFrame(response.data) if response.data else pd.DataFrame()

def update_task_status(task_id, new_status, remarks=None):
    try:
        data = {"status": new_status}
        if remarks: data["staff_remarks"] = remarks
        supabase.table("tasks").update(data).eq("id", task_id).execute()
        return True
    except: return False

def update_task_full(task_id, new_desc, new_date, new_prio, new_remarks, new_assign, new_points, new_subject, new_coord, new_proj, is_manager):
    try:
        data = {
            "task_desc": new_desc,
            "due_date": str(new_date),
            "priority": new_prio,
            "staff_remarks": new_remarks,
            "points": new_points,
            "email_subject": new_subject,
            "coordinator": new_coord,
            "project_ref": new_proj
        }
        if is_manager and new_assign:
            data["assigned_to"] = new_assign
            
        supabase.table("tasks").update(data).eq("id", task_id).execute()
        return True
    except Exception as e:
        st.error(f"Update failed: {e}")
        return False

# --- MAIN APP ---
def main():
    if 'logged_in' not in st.session_state: st.session_state['logged_in'] = False
    if 'user_role' not in st.session_state: st.session_state['user_role'] = None
    if 'user_name' not in st.session_state: st.session_state['user_name'] = None

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
                        else: st.error("🚫 Access Denied.")
                    else: st.error(f"🚫 Restricted Access. {COMPANY_DOMAIN} only.")
    
    else:
        current_user = st.session_state['user']
        user_role = st.session_state['user_role']
        user_name = st.session_state['user_name']
        is_manager = (user_role == 'manager')
        
        with st.sidebar:
            st.markdown(f"### 💼 RBS Workspace")
            role_label = "Manager" if is_manager else "Team Member"
            st.caption(f"{user_name} ({role_label})")
            
            # --- MENU ---
            menu_options = ["Dashboard", "New Task"] 
            menu_icons = ["journal-bookmark", "plus-circle"]
            
            if is_manager:
                menu_options.append("Sync Roadmap")
                menu_icons.append("cloud-arrow-down")
                menu_options.append("Team Master") 
                menu_icons.append("people-fill")

            nav_mode = option_menu(
                menu_title=None, options=menu_options, icons=menu_icons, 
                menu_icon="cast", default_index=0,
                styles={"container": {"padding": "0!important", "background-color": "#fafafa"},
                        "icon": {"color": "black", "font-size": "16px"}, 
                        "nav-link": {"font-size": "14px", "text-align": "left", "margin":"0px"},
                        "nav-link-selected": {"background-color": "#ff4b4b"}}
            )
            
            st.divider()
            st.markdown("**🤖 Assistant**")
            if st.button("Generate Briefing", use_container_width=True):
                with st.spinner("Analyzing..."):
                    q_ai = supabase.table("tasks").select("*").eq("assigned_to", current_user) if not is_manager else supabase.table("tasks").select("*")
                    resp_ai = q_ai.execute()
                    df_ai = pd.DataFrame(resp_ai.data) if resp_ai.data else pd.DataFrame()
                    if not df_ai.empty: st.info(get_ai_summary(df_ai))
                    else: st.warning("No data.")
            
            st.write("") 
            if st.button("Logout", use_container_width=True):
                st.session_state['logged_in'] = False; st.rerun()

        if nav_mode == "Sync Roadmap" and is_manager:
            st.header("🔗 Google Sheets Sync")
            st.info("Update your Google Sheet 'ROADMAP' tab, then click below.")
            if st.button("🚀 Pull Latest Roadmap", type="primary"):
                with st.spinner("Syncing..."):
                    success, msg = sync_projects()
                    if success: st.success(msg)
                    else: st.error(msg)

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
                            if success: st.toast(msg, icon="✅"); time.sleep(1); st.rerun()
                            else: st.error(msg)
                        else: st.warning("Invalid Email or Name.")

            st.divider()
            st.subheader("Current Team List")
            users = supabase.table("user_master").select("*").order("name").execute().data
            if users:
                df_users = pd.DataFrame(users)
                for i, u in df_users.iterrows():
                    with st.container(border=True):
                        c1, c2, c3, c4 = st.columns([2, 3, 1, 1])
                        c1.write(f"**{u['name']}**"); c2.write(f"`{u['email']}`"); c3.caption(f"_{u['role']}_")
                        btn_label = "🔴 Deactivate" if u['status'] == 'active' else "🟢 Activate"
                        if c4.button(btn_label, key=f"tog_{u['email']}"):
                            toggle_user_status(u['email'], u['status']); st.rerun()
            else: st.info("No users found.")

        # --- SEPARATE NEW TASK PAGE ---
        elif nav_mode == "New Task":
            st.header("✨ Create New Task")
            
            # Efficient Load
            _, all_projects, all_coords = load_data_efficiently(None) 
            
            # Toggles OUTSIDE form
            col_t1, col_t2 = st.columns(2)
            with col_t1: is_new_proj = st.checkbox("➕ New Project?", key="tog_p_page")
            with col_t2: is_new_coord = st.checkbox("➕ New Coordinator?", key="tog_c_page")

            with st.form("new_task_page_form", clear_on_submit=True):
                st.text_input("Task Description", placeholder="What needs to be done?", key="nt_desc")
                
                c2, c3 = st.columns(2)
                with c2:
                    if is_new_proj: selected_project = st.text_input("Type Project Name", key="nt_p_txt")
                    else: selected_project = st.selectbox("Project", all_projects, key="nt_p_sel")
                with c3:
                    if is_new_coord: final_coordinator = st.text_input("Type Coordinator Name", key="nt_c_txt")
                    else: final_coordinator = st.selectbox("Point Coordinator", all_coords, key="nt_c_sel")

                c4, c5 = st.columns(2)
                with c4: email_subj = st.text_input("Email Subject", placeholder="Optional", key="nt_sub")
                with c5: points = st.text_area("Detailed Points", height=1, placeholder="One per line...", key="nt_pts")

                c6, c7, c8 = st.columns(3)
                with c6:
                    all_users = get_active_users()
                    assign_options = ["Unassigned"] + all_users
                    d_idx = assign_options.index(current_user) if current_user in assign_options else 0
                    assign_to = st.selectbox("Assign To", assign_options, index=d_idx, key="nt_ass")
                    final_assign = assign_to if assign_to != "Unassigned" else None
                with c7: prio = st.selectbox("Priority", ["🔥 High", "⚡ Medium", "🧊 Low"], key="nt_pri")
                with c8: due = st.date_input("Due Date", value=date.today(), key="nt_due")

                submitted = st.form_submit_button("🚀 Add Task", type="primary", use_container_width=True)

                if submitted:
                    if st.session_state.nt_desc:
                        proj_save = selected_project if selected_project else "General"
                        coord_save = final_coordinator if final_coordinator else "General"
                        if add_task(current_user, final_assign, st.session_state.nt_desc, prio, due, proj_save, coord_save, email_subj, points):
                            st.toast("✅ Task Added Successfully!")
                            time.sleep(0.1)
                    else:
                        st.warning("Description required.")

        # --- DASHBOARD VIEW (MAIN) ---
        elif nav_mode == "Dashboard":
            
            # 1. OPTIMIZED DATA FETCH
            view_email = None
            if is_manager:
                c_filter, c_title = st.columns([1, 3])
                with c_filter:
                    all_users = get_active_users()
                    view_target = st.selectbox("View Diary For:", ["All Users"] + all_users)
                    if view_target != "All Users": view_email = view_target
                with c_title: st.title("📔 Operational Diary")
            else:
                st.title("📔 My Diary")
                view_email = current_user
            
            # --- SUPER FAST ONE-TIME LOAD + CLEANING ---
            df, all_projects, all_coords = load_data_efficiently(view_email)

            # --- 2. NEW TASK EXPANDER ---
            with st.expander("➕ Create New Task", expanded=False):
                col_t1, col_t2 = st.columns(2)
                with col_t1: is_new_proj_d = st.checkbox("➕ New Project?", key="tog_pd")
                with col_t2: is_new_coord_d = st.checkbox("➕ New Coordinator?", key="tog_cd")

                with st.form("dash_quick_add", clear_on_submit=True):
                    st.text_input("Task Description", placeholder="What needs to be done?", key="d_desc")
                    
                    c2, c3 = st.columns(2)
                    with c2:
                        if is_new_proj_d: selected_project = st.text_input("Type Project Name", key="d_p_txt")
                        else: selected_project = st.selectbox("Project", all_projects, key="d_p_sel")

                    with c3:
                        if is_new_coord_d: final_coordinator = st.text_input("Type Coordinator Name", key="d_c_txt")
                        else: final_coordinator = st.selectbox("Point Coordinator", all_coords, key="d_c_sel")

                    c4, c5 = st.columns(2)
                    with c4: email_subj = st.text_input("Email Subject", placeholder="Optional", key="d_sub")
                    with c5: points = st.text_area("Detailed Points", height=1, placeholder="One per line...", key="d_pts")

                    c6, c7, c8, c9 = st.columns([2, 1, 1, 1])
                    with c6:
                        all_users_list = get_active_users()
                        assign_opts = ["Unassigned"] + all_users_list
                        d_idx = assign_opts.index(current_user) if current_user in assign_opts else 0
                        assign_to = st.selectbox("Assign To", assign_opts, index=d_idx, key="d_ass")
                        final_assign = assign_to if assign_to != "Unassigned" else None
                    with c7: prio = st.selectbox("Priority", ["🔥 High", "⚡ Medium", "🧊 Low"], key="d_pri")
                    with c8: due = st.date_input("Due Date", value=date.today(), key="d_due")
                    with c9:
                        st.write("")
                        st.write("")
                        submitted = st.form_submit_button("🚀 Add", type="primary", use_container_width=True)
                    
                    if submitted:
                        if st.session_state.d_desc:
                            proj_save = selected_project if selected_project else "General"
                            coord_save = final_coordinator if final_coordinator else "General"
                            if add_task(current_user, final_assign, st.session_state.d_desc, prio, due, proj_save, coord_save, email_subj, points):
                                st.toast("✅ Added!")
                                time.sleep(0.01)
                                st.rerun()
                        else:
                            st.warning("Desc required.")

            # --- 3. TASK LIST RENDER ---
            if not df.empty:
                # Dates are already cleaned in load_data_efficiently, but just to be safe for display logic
                today_ts = pd.Timestamp.now().normalize()
                active_df = df[df['status'] != 'Completed'].copy()
                
                c_all = len(active_df)
                c_today = len(active_df[active_df['due_date'] == today_ts])
                c_tmrw = len(active_df[active_df['due_date'] == today_ts + pd.Timedelta(days=1)])
                c_over = len(active_df[active_df['due_date'] < today_ts])
                
                selected_filter = option_menu(
                    menu_title=None,
                    options=[f"All Pending ({c_all})", f"Today ({c_today})", f"Tomorrow ({c_tmrw})", f"Overdue ({c_over})"],
                    icons=["folder", "lightning", "calendar", "exclamation-triangle"],
                    orientation="horizontal",
                    styles={"container": {"padding": "0!important", "background-color": "#fafafa"}}
                )
                
                if "Today" in selected_filter: filtered = active_df[active_df['due_date'] == today_ts]
                elif "Tomorrow" in selected_filter: filtered = active_df[active_df['due_date'] == today_ts + pd.Timedelta(days=1)]
                elif "Overdue" in selected_filter: filtered = active_df[active_df['due_date'] < today_ts]
                else: filtered = active_df
                
                st.write("")
                
                if filtered.empty: 
                    st.info(f"✅ No tasks found for '{selected_filter}'.")
                else:
                    # SCROLLABLE CONTAINER
                    with st.container(height=600):
                        for index, row in filtered.iterrows():
                            # Safe date formatting
                            try:
                                d_str = row['due_date'].strftime('%d-%b')
                            except:
                                d_str = "No Date"
                                
                            proj = row.get('project_ref', 'General')
                            priority_icon = "🔴" if "High" in row['priority'] else "🟡" if "Medium" in row['priority'] else "🔵"
                            assign_display = row['assigned_to'] if row['assigned_to'] else "Unassigned"
                            assign_label = f" ➝ {assign_display.split('@')[0].title()}" if (is_manager) else ""
                            
                            with st.expander(f"{priority_icon}  **{d_str}** | {row['task_desc']} _({proj}){assign_label}_"):
                                
                                with st.form(key=f"edit_{row['id']}"):
                                    e1, e2 = st.columns([2, 1])
                                    new_desc = e1.text_input("Desc", value=row['task_desc'])
                                    new_rem = e2.text_input("Rem", value=row['staff_remarks'] if row['staff_remarks'] else "")
                                    
                                    e3, e4 = st.columns(2)
                                    # Edit Project + Toggle
                                    curr_proj = row.get('project_ref', 'General')
                                    edit_projs = sorted(list(set(all_projects + [curr_proj])))
                                    ep1, ep2 = e3.columns([3,1])
                                    with ep2: 
                                        st.write("")
                                        is_new_p_e = st.checkbox("New", key=f"np_{row['id']}")
                                    with ep1:
                                        if is_new_p_e: new_proj = st.text_input("Project", key=f"tp_{row['id']}")
                                        else: 
                                            try: p_idx = edit_projs.index(curr_proj)
                                            except: p_idx = 0
                                            new_proj = st.selectbox("Project", edit_projs, index=p_idx, key=f"sp_{row['id']}")

                                    # Edit Coord + Toggle
                                    curr_coord = row.get('coordinator', '') if pd.notna(row.get('coordinator')) else "General"
                                    edit_coords = sorted(list(set(all_coords + [curr_coord])))
                                    ec1, ec2 = e4.columns([3,1])
                                    with ec2:
                                        st.write("")
                                        is_new_c_e = st.checkbox("New", key=f"nc_{row['id']}")
                                    with ec1:
                                        if is_new_c_e: new_coord = st.text_input("Coord", key=f"tc_{row['id']}")
                                        else:
                                            try: c_idx = edit_coords.index(curr_coord)
                                            except: c_idx = 0
                                            new_coord = st.selectbox("Coord", edit_coords, index=c_idx, key=f"sc_{row['id']}")

                                    curr_pts = row.get('points', '') if pd.notna(row.get('points')) else ""
                                    new_points = st.text_area("Points", value=curr_pts, height=80)

                                    b1, b2 = st.columns(2)
                                    if b1.form_submit_button("💾 Save"):
                                        final_c = new_coord if new_coord else curr_coord
                                        final_p = new_proj if new_proj else curr_proj
                                        if update_task_full(row['id'], new_desc, row['due_date'], row['priority'], new_rem, row['assigned_to'], new_points, row['email_subject'], final_c, final_p, is_manager):
                                            st.toast("Updated!")
                                            time.sleep(0.01)
                                            st.rerun()
                                    
                                    if b2.form_submit_button("✅ Done"):
                                        update_task_status(row['id'], "Completed", new_rem)
                                        st.rerun()

            else: st.info("👋 No active tasks found.")

if __name__ == "__main__":
    main()
