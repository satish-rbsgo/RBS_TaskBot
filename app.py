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
    
    .stButton button { width: 100%; border-radius: 5px; height: 2.2rem; }
    section[data-testid="stSidebar"] .block-container { padding-top: 2rem; }
    
    /* Compact spacing for columns */
    div[data-testid="column"] { padding-bottom: 5px; }
    
    /* Custom Scrollbar */
    div[data-testid="stVerticalBlock"] > div[style*="overflow"]::-webkit-scrollbar { width: 6px; }
    div[data-testid="stVerticalBlock"] > div[style*="overflow"]::-webkit-scrollbar-thumb { background-color: #ccc; border-radius: 3px; }
    
    /* Vertical Align Checkbox with Input */
    div[data-testid="stCheckbox"] { margin-top: 28px; }
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
            data = { "name": p_name, "status": p_status, "description": p_desc, "vendor": p_vendor }
            try:
                supabase.table("projects").upsert(data, on_conflict="name").execute()
                count += 1
            except Exception as row_error:
                print(f"Row skipped {p_name}: {row_error}")
                continue
        get_projects_master.clear()
        return True, f"✅ Synced {count} Projects!"
    except Exception as e:
        return False, f"❌ Sync Error: {str(e)}"

# --- OPTIMIZED DATA LOADING ---
@st.cache_data(ttl=300)
def get_projects_master():
    try:
        response = supabase.table("projects").select("name").execute()
        return [row['name'] for row in response.data] if response.data else []
    except: return []

def load_data_efficiently(target_email=None):
    query = supabase.table("tasks").select("*").order("due_date", desc=False)
    if target_email: query = query.eq("assigned_to", target_email)
    response = query.execute()
    df = pd.DataFrame(response.data) if response.data else pd.DataFrame()

    if not df.empty:
        # Critical Fix: Date Handling
        df['due_date'] = pd.to_datetime(df['due_date'], errors='coerce')
        df['due_date'] = df['due_date'].fillna(pd.Timestamp.now().normalize())
        
        used_coords = df['coordinator'].dropna().unique().tolist()
        used_projs = df['project_ref'].dropna().unique().tolist()
    else:
        used_coords = []
        used_projs = []

    master_projs = get_projects_master()
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
            "created_by": created_by, "assigned_to": assigned_to, "task_desc": task_desc,
            "status": "Open", "priority": priority, "due_date": final_date,
            "project_ref": final_project, "staff_remarks": "", "manager_remarks": "",
            "coordinator": final_coord, "email_subject": email_subject, "points": points
        }
        supabase.table("tasks").insert(data).execute()
        return True
    except Exception as e:
        st.error(f"Add Task Error: {e}")
        return False

def get_tasks(target_email=None):
    return load_data_efficiently(target_email)[0]

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
            "task_desc": new_desc, "due_date": str(new_date), "priority": new_prio,
            "staff_remarks": new_remarks, "points": new_points, "email_subject": new_subject,
            "coordinator": new_coord, "project_ref": new_proj
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

    # --- FIX: LOGIN PLACEHOLDER (Prevents Ghosting) ---
    login_placeholder = st.empty()

    if not st.session_state['logged_in']:
        with login_placeholder.container():
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
                                login_placeholder.empty() # Clear UI instantly
                                st.rerun()
                            else: st.error("🚫 Access Denied.")
                        else: st.error(f"🚫 Restricted Access. {COMPANY_DOMAIN} only.")
    
    else:
        # --- DASHBOARD LOGIC START ---
        current_user = st.session_state['user']
        user_role = st.session_state['user_role']
        user_name = st.session_state['user_name']
        is_manager = (user_role == 'manager')
        
        with st.sidebar:
            st.markdown(f"### 💼 RBS Workspace")
            role_label = "Manager" if is_manager else "Team Member"
            st.caption(f"{user_name} ({role_label})")
            
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
                        else: st.warning("Invalid.")

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

        # --- SEPARATE NEW TASK PAGE ---
        elif nav_mode == "New Task":
            st.header("✨ Create New Task")
            _, all_projects, all_coords = load_data_efficiently(None) 
            
            # REMOVED FORM WRAPPER to allow instant interactivity
            task_desc = st.text_input("Task Description", placeholder="What needs to be done?", key="nt_desc")
            
            c2, c3 = st.columns(2)
            # Side-by-Side Project
            with c2:
                p_inp, p_chk = st.columns([4, 1])
                with p_chk:
                    is_new_proj = st.checkbox("New", key="nt_p_chk")
                with p_inp:
                    if is_new_proj: selected_project = st.text_input("Project", key="nt_p_txt")
                    else: selected_project = st.selectbox("Project", all_projects, key="nt_p_sel")
            
            # Side-by-Side Coordinator
            with c3:
                c_inp, c_chk = st.columns([4, 1])
                with c_chk:
                    is_new_coord = st.checkbox("New", key="nt_c_chk")
                with c_inp:
                    if is_new_coord: final_coordinator = st.text_input("Coordinator", key="nt_c_txt")
                    else: final_coordinator = st.selectbox("Coordinator", all_coords, key="nt_c_sel")

            c4, c5 = st.columns(2)
            email_subj = c4.text_input("Email Subject", placeholder="Optional", key="nt_sub")
            points = c5.text_area("Detailed Points", height=1, placeholder="One per line...", key="nt_pts")

            c6, c7, c8 = st.columns(3)
            with c6:
                all_users = get_active_users()
                assign_options = ["Unassigned"] + all_users
                d_idx = assign_options.index(current_user) if current_user in assign_options else 0
                assign_to = st.selectbox("Assign To", assign_options, index=d_idx, key="nt_ass")
                final_assign = assign_to if assign_to != "Unassigned" else None
            with c7: prio = st.selectbox("Priority", ["🔥 High", "⚡ Medium", "🧊 Low"], key="nt_pri")
            with c8: due = st.date_input("Due Date", value=date.today(), key="nt_due")

            # Simple Button instead of Form Submit to allow dynamic UI updates
            if st.button("🚀 Add Task", type="primary", use_container_width=True):
                if task_desc:
                    proj_save = selected_project if selected_project else "General"
                    coord_save = final_coordinator if final_coordinator else "General"
                    if add_task(current_user, final_assign, task_desc, prio, due, proj_save, coord_save, email_subj, points):
                        st.toast("✅ Task Added!"); time.sleep(0.1); st.rerun()
                else:
                    st.warning("Description required.")

        # --- DASHBOARD VIEW (MAIN) ---
        elif nav_mode == "Dashboard":
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
            
            df, all_projects, all_coords = load_data_efficiently(view_email)

            # --- 2. NEW TASK EXPANDER (NO FORM WRAPPER FOR INSTANT TOGGLES) ---
            with st.expander("➕ Create New Task", expanded=False):
                d_desc = st.text_input("Task Description", placeholder="What needs to be done?", key="d_desc")
                
                c2, c3 = st.columns(2)
                # Dashboard Project - Side by Side
                with c2:
                    p_inp, p_chk = st.columns([4, 1])
                    with p_chk:
                        is_new_proj_d = st.checkbox("New", key="d_p_chk")
                    with p_inp:
                        if is_new_proj_d: selected_project = st.text_input("Project", key="d_p_txt")
                        else: selected_project = st.selectbox("Project", all_projects, key="d_p_sel")
                
                # Dashboard Coordinator - Side by Side
                with c3:
                    c_inp, c_chk = st.columns([4, 1])
                    with c_chk:
                        is_new_coord_d = st.checkbox("New", key="d_c_chk")
                    with c_inp:
                        if is_new_coord_d: final_coordinator = st.text_input("Coordinator", key="d_c_txt")
                        else: final_coordinator = st.selectbox("Coordinator", all_coords, key="d_c_sel")

                c4, c5 = st.columns(2)
                email_subj = c4.text_input("Email Subject", placeholder="Optional", key="d_sub")
                points = c5.text_area("Detailed Points", height=1, placeholder="One per line...", key="d_pts")
                
                c6, c7, c8 = st.columns(3)
                with c6:
                    all_users_list = get_active_users()
                    assign_opts = ["Unassigned"] + all_users_list
                    d_idx = assign_opts.index(current_user) if current_user in assign_opts else 0
                    assign_to = st.selectbox("Assign To", assign_opts, index=d_idx, key="d_ass")
                    final_assign = assign_to if assign_to != "Unassigned" else None
                with c7: prio = st.selectbox("Priority", ["🔥 High", "⚡ Medium", "🧊 Low"], key="d_pri")
                with c8: due = st.date_input("Due Date", value=date.today(), key="d_due")
                
                # Simple Button triggers rerun
                if st.button("🚀 Add", type="primary", use_container_width=True, key="d_add_btn"):
                    if d_desc:
                        proj_save = selected_project if selected_project else "General"
                        coord_save = final_coordinator if final_coordinator else "General"
                        if add_task(current_user, final_assign, d_desc, prio, due, proj_save, coord_save, email_subj, points):
                            st.toast("✅ Added!"); time.sleep(0.01); st.rerun()
                    else:
                        st.warning("Desc required.")

            # --- 3. TASK LIST RENDER ---
            if not df.empty:
                today_ts = pd.Timestamp.now().normalize()
                active_df = df[df['status'] != 'Completed'].copy()
                completed_df = df[df['status'] == 'Completed'].copy()
                
                c_all, c_done = len(active_df), len(completed_df)
                c_today = len(active_df[active_df['due_date'] == today_ts])
                c_tmrw = len(active_df[active_df['due_date'] == today_ts + pd.Timedelta(days=1)])
                c_over = len(active_df[active_df['due_date'] < today_ts])
                
                selected_filter = option_menu(
                    menu_title=None,
                    options=[f"Pending ({c_all})", f"Today ({c_today})", f"Tomorrow ({c_tmrw})", f"Overdue ({c_over})", f"Completed ({c_done})"],
                    icons=["folder", "lightning", "calendar", "exclamation-triangle", "check-circle"],
                    orientation="horizontal",
                    styles={"container": {"padding": "0!important", "background-color": "#fafafa"}}
                )
                
                final_view_df = completed_df if "Completed" in selected_filter else \
                                active_df[active_df['due_date'] == today_ts] if "Today" in selected_filter else \
                                active_df[active_df['due_date'] == today_ts + pd.Timedelta(days=1)] if "Tomorrow" in selected_filter else \
                                active_df[active_df['due_date'] < today_ts] if "Overdue" in selected_filter else active_df
                
                st.write("")
                if final_view_df.empty: st.info(f"✅ No tasks found for '{selected_filter}'.")
                else:
                    with st.container(height=600):
                        for index, row in final_view_df.iterrows():
                            try: d_str = row['due_date'].strftime('%d-%b')
                            except: d_str = "No Date"
                            proj = row.get('project_ref', 'General')
                            icon = "🟢" if "Completed" in selected_filter else "🔴" if "High" in row['priority'] else "🟡" if "Medium" in row['priority'] else "🔵"
                            assign_label = f" ➝ {row['assigned_to'].split('@')[0].title()}" if (is_manager and row['assigned_to']) else ""
                            
                            with st.expander(f"{icon}  **{d_str}** | {row['task_desc']} _({proj}){assign_label}_"):
                                with st.form(key=f"edit_{row['id']}"):
                                    # COMPACT ROW 1
                                    c1, c2, c3 = st.columns([5, 2, 2])
                                    new_desc = c1.text_input("Desc", value=row['task_desc'], label_visibility="collapsed", placeholder="Task Description")
                                    prio_idx = ["🔥 High", "⚡ Medium", "🧊 Low"].index(row['priority']) if row['priority'] in ["🔥 High", "⚡ Medium", "🧊 Low"] else 1
                                    new_prio = c2.selectbox("Prio", ["🔥 High", "⚡ Medium", "🧊 Low"], index=prio_idx, label_visibility="collapsed")
                                    new_date = c3.date_input("Date", value=row['due_date'], label_visibility="collapsed")

                                    # COMPACT ROW 2
                                    c4, c5, c6 = st.columns([3, 3, 3])
                                    # Project - Edit with Toggle
                                    curr_proj = row.get('project_ref', 'General')
                                    edit_projs = sorted(list(set(all_projects + [curr_proj])))
                                    with c4:
                                        p_inp_col, p_chk_col = st.columns([5, 1])
                                        with p_chk_col:
                                            is_new_p = st.checkbox("Nw", key=f"np_{row['id']}")
                                        with p_inp_col:
                                            if is_new_p: new_proj = st.text_input("Proj", key=f"tp_{row['id']}", label_visibility="collapsed")
                                            else: 
                                                try: px = edit_projs.index(curr_proj)
                                                except: px = 0
                                                new_proj = st.selectbox("Proj", edit_projs, index=px, key=f"sp_{row['id']}", label_visibility="collapsed")
                                    
                                    # Coord - Edit with Toggle
                                    curr_coord = row.get('coordinator', '') if pd.notna(row.get('coordinator')) else "General"
                                    edit_coords = sorted(list(set(all_coords + [curr_coord])))
                                    with c5:
                                        c_inp_col, c_chk_col = st.columns([5, 1])
                                        with c_chk_col:
                                            is_new_c = st.checkbox("Nw", key=f"nc_{row['id']}")
                                        with c_inp_col:
                                            if is_new_c: new_coord = st.text_input("Coord", key=f"tc_{row['id']}", label_visibility="collapsed")
                                            else:
                                                try: cx = edit_coords.index(curr_coord)
                                                except: cx = 0
                                                new_coord = st.selectbox("Coord", edit_coords, index=cx, key=f"sc_{row['id']}", label_visibility="collapsed")

                                    # Assignee
                                    if is_manager:
                                        all_users_list = get_active_users()
                                        assign_opts = ["Unassigned"] + all_users_list
                                        try: ax = assign_opts.index(row['assigned_to'] if row['assigned_to'] else "Unassigned")
                                        except: ax = 0
                                        new_assign_sel = c6.selectbox("Assign", assign_opts, index=ax, label_visibility="collapsed")
                                        new_assign = new_assign_sel if new_assign_sel != "Unassigned" else None
                                    else:
                                        new_assign = row['assigned_to']
                                        c6.text_input("Assign", value=new_assign, disabled=True, label_visibility="collapsed")

                                    # COMPACT ROW 3
                                    curr_rem = row['staff_remarks'] if row['staff_remarks'] else ""
                                    new_rem = st.text_input("Remarks", value=curr_rem, placeholder="Updates...", label_visibility="collapsed")
                                    curr_pts = row.get('points', '') if pd.notna(row.get('points')) else ""
                                    new_points = st.text_area("Details", value=curr_pts, height=68, label_visibility="collapsed", placeholder="Detailed Points...")

                                    # ACTIONS
                                    b1, b2, b3 = st.columns([1, 2, 1])
                                    if b1.form_submit_button("💾 Save"):
                                        final_c = new_coord if new_coord else curr_coord
                                        final_p = new_proj if new_proj else curr_proj
                                        if update_task_full(row['id'], new_desc, new_date, new_prio, new_rem, new_assign, new_points, row['email_subject'], final_c, final_p, is_manager):
                                            st.toast("Saved!"); time.sleep(0.01); st.rerun()

                                    if "Completed" not in selected_filter:
                                        close_rem = b2.text_input("Close Rem", placeholder="Closing Note...", label_visibility="collapsed", key=f"crm_{row['id']}")
                                        if b3.form_submit_button("✅ Close", type="primary"):
                                            if close_rem:
                                                update_task_status(row['id'], "Completed", close_rem)
                                                st.toast("Completed!"); time.sleep(0.1); st.rerun()
                                            else: st.warning("Note required.")
                                    else:
                                        st.write("") 
                                        if b3.form_submit_button("🔄 Reinstate"):
                                            update_task_status(row['id'], "Open", row['staff_remarks'])
                                            st.toast("Restored!"); time.sleep(0.1); st.rerun()

            else: st.info("👋 No active tasks found.")

if __name__ == "__main__":
    main()
