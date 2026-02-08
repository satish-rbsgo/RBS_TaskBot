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
            
        get_projects.clear()
        return True, f"✅ Synced {count} Projects!"
    except Exception as e:
        return False, f"❌ Sync Error: {str(e)}"

@st.cache_data(ttl=60)
def get_projects():
    try:
        response = supabase.table("projects").select("name").execute()
        return [row['name'] for row in response.data] if response.data else []
    except: return []

# --- HELPER: GET UNIQUE VALUES ---
def get_unique_column_values(column_name):
    try:
        response = supabase.table("tasks").select(column_name).execute()
        if response.data:
            vals = list(set([row[column_name] for row in response.data if row[column_name]]))
            vals.sort()
            return vals
        return []
    except: return []

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
            
            # --- DASHBOARD IS THE MAIN VIEW (New Task Removed from Sidebar) ---
            menu_options = ["Dashboard"] 
            menu_icons = ["journal-bookmark"]
            
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
                    tasks_to_analyze = get_tasks(None) if is_manager else get_tasks(current_user)
                    if not tasks_to_analyze.empty: st.info(get_ai_summary(tasks_to_analyze))
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

        # --- DASHBOARD VIEW (MAIN) ---
        elif nav_mode == "Dashboard":
            # --- 1. NEW TASK SECTION (Collapsible & Auto-Clearing) ---
            with st.expander("➕ Create New Task", expanded=False):
                # Toggles for New Project/Coordinator - Outside form to update UI
                col_t1, col_t2 = st.columns(2)
                with col_t1: is_new_proj = st.toggle("Type New Project?", key="tog_p")
                with col_t2: is_new_coord = st.toggle("Type New Coordinator?", key="tog_c")

                with st.form("quick_add_task", clear_on_submit=True):
                    # Description
                    st.text_input("Task Description", placeholder="What needs to be done?", key="new_desc")
                    
                    # Row 2: Project & Coordinator
                    c2, c3 = st.columns(2)
                    
                    with c2:
                        if is_new_proj:
                            selected_project = st.text_input("New Project Name", key="n_p_txt")
                        else:
                            synced_projects = get_projects()
                            used_projects = get_unique_column_values("project_ref")
                            all_projects = sorted(list(set(synced_projects + used_projects + ["General"])))
                            selected_project = st.selectbox("Project", all_projects, key="n_p_sel")

                    with c3:
                        if is_new_coord:
                            final_coordinator = st.text_input("New Coordinator", key="n_c_txt")
                        else:
                            existing_coords = get_unique_column_values("coordinator")
                            base_coords = ["Sales Team", "Client", "Support Team", "Internal", "Management"]
                            all_coords = sorted(list(set(base_coords + existing_coords)))
                            final_coordinator = st.selectbox("Point Coordinator", all_coords, key="n_c_sel")

                    # Row 3: Meta
                    c4, c5 = st.columns(2)
                    with c4: email_subj = st.text_input("Email Subject", placeholder="Optional", key="n_sub")
                    with c5: points = st.text_area("Detailed Points", height=1, placeholder="One per line...", key="n_pts")

                    # Row 4: Assign & Save
                    c6, c7, c8, c9 = st.columns([2, 1, 1, 1])
                    with c6:
                        all_users = get_active_users()
                        assign_options = ["Unassigned"] + all_users
                        d_idx = assign_options.index(current_user) if current_user in assign_options else 0
                        assign_to = st.selectbox("Assign To", assign_options, index=d_idx, key="n_ass")
                        final_assign = assign_to if assign_to != "Unassigned" else None
                    with c7: prio = st.selectbox("Priority", ["🔥 High", "⚡ Medium", "🧊 Low"], key="n_pri")
                    with c8: due = st.date_input("Due Date", value=date.today(), key="n_due")
                    with c9:
                        st.write("") # Spacer
                        st.write("") # Spacer
                        # Form submit button
                        submitted = st.form_submit_button("🚀 Add Task", type="primary", use_container_width=True)
                    
                    if submitted:
                        if st.session_state.new_desc:
                            # Logic to pick correct value based on toggle state
                            proj_save = selected_project if selected_project else "General"
                            coord_save = final_coordinator if final_coordinator else "General"
                            
                            # Fast Save
                            if add_task(current_user, final_assign, st.session_state.new_desc, prio, due, proj_save, coord_save, email_subj, points):
                                st.toast("✅ Task Added!")
                                time.sleep(0.5)
                                st.rerun()
                        else:
                            st.warning("Description required.")

            # --- 2. DIARY VIEW ---
            df = pd.DataFrame()
            if is_manager:
                c_filter, c_title = st.columns([1, 3])
                with c_filter:
                    all_users = get_active_users()
                    view_target = st.selectbox("View Diary For:", ["All Users"] + all_users)
                with c_title: st.title("📔 Operational Diary")
                df = get_tasks(None) if view_target == "All Users" else get_tasks(view_target)
            else:
                st.title("📔 My Diary")
                df = get_tasks(current_user)
            
            if not df.empty:
                df['due_date'] = pd.to_datetime(df['due_date'], errors='coerce')
                today_ts = pd.Timestamp.now().normalize()
                active_df = df[df['status'] != 'Completed'].copy()
                
                # Filters
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
                
                # Filter Logic
                if "Today" in selected_filter: filtered = active_df[active_df['due_date'] == today_ts]
                elif "Tomorrow" in selected_filter: filtered = active_df[active_df['due_date'] == today_ts + pd.Timedelta(days=1)]
                elif "Overdue" in selected_filter: filtered = active_df[active_df['due_date'] < today_ts]
                else: filtered = active_df
                
                st.write("")
                
                if filtered.empty: 
                    st.info(f"✅ No tasks found for '{selected_filter}'.")
                else:
                    # --- SCROLLABLE CONTAINER (FIXED HEIGHT) ---
                    # This keeps the filters/header stuck at the top while tasks scroll
                    with st.container(height=600):
                        filtered = filtered.sort_values(by=["due_date", "priority"], ascending=[True, True])
                        
                        for index, row in filtered.iterrows():
                            d_str = row['due_date'].strftime('%d-%b')
                            proj = row.get('project_ref', 'General')
                            if not proj: proj = "General"
                            priority_icon = "🔴" if "High" in row['priority'] else "🟡" if "Medium" in row['priority'] else "🔵"
                            
                            assign_display = row['assigned_to'] if row['assigned_to'] else "Unassigned"
                            assign_label = f" ➝ {assign_display.split('@')[0].title()}" if (is_manager) else ""
                            
                            with st.expander(f"{priority_icon}  **{d_str}** | {row['task_desc']} _({proj}){assign_label}_"):
                                
                                with st.form(key=f"edit_form_{row['id']}"):
                                    c_edit_1, c_edit_2 = st.columns([2, 1])
                                    new_desc = c_edit_1.text_input("Description", value=row['task_desc'])
                                    new_rem = c_edit_2.text_input("Remarks", value=row['staff_remarks'] if row['staff_remarks'] else "")
                                    
                                    # Edit Logic: Details
                                    c3, c4 = st.columns(2)
                                    curr_points = row.get('points', '') if pd.notna(row.get('points')) else ""
                                    new_points = c3.text_area("Detailed Points", value=curr_points, height=100)
                                    
                                    # Edit Logic: Coordinator (Toggle)
                                    curr_coord = row.get('coordinator', '') if pd.notna(row.get('coordinator')) else "General"
                                    existing_coords_edit = get_unique_column_values("coordinator")
                                    all_coords_edit = sorted(list(set(["General"] + existing_coords_edit + [curr_coord])))
                                    
                                    # Toggle for Edit Coordinator
                                    c4a, c4b = c4.columns([3, 1])
                                    with c4b: edit_new_coord = st.checkbox("New?", key=f"chk_nc_{row['id']}")
                                    with c4a:
                                        if edit_new_coord:
                                            new_coord = st.text_input("Coord Name", key=f"txt_nc_{row['id']}")
                                        else:
                                            try: c_idx = all_coords_edit.index(curr_coord)
                                            except: c_idx = 0
                                            new_coord = st.selectbox("Coordinator", all_coords_edit, index=c_idx, key=f"sel_nc_{row['id']}")

                                    # Edit Logic: Project (Toggle)
                                    c5, c6 = st.columns(2)
                                    curr_proj = row.get('project_ref', 'General')
                                    synced_projects_edit = get_projects()
                                    used_projects_edit = get_unique_column_values("project_ref")
                                    all_projects_edit = sorted(list(set(synced_projects_edit + used_projects_edit + ["General"] + [curr_proj])))
                                    
                                    # Toggle for Edit Project
                                    c5a, c5b = c5.columns([3, 1])
                                    with c5b: edit_new_proj = st.checkbox("New?", key=f"chk_np_{row['id']}")
                                    with c5a:
                                        if edit_new_proj:
                                            new_proj = st.text_input("Proj Name", key=f"txt_np_{row['id']}")
                                        else:
                                            try: p_idx = all_projects_edit.index(curr_proj)
                                            except: p_idx = 0
                                            new_proj = st.selectbox("Project", all_projects_edit, index=p_idx, key=f"sel_np_{row['id']}")

                                    curr_subj = row.get('email_subject', '') if pd.notna(row.get('email_subject')) else ""
                                    new_subject = c6.text_input("Email Subject", value=curr_subj)

                                    c7, c8, c9 = st.columns(3)
                                    new_date = c7.date_input("Due Date", value=row['due_date'])
                                    
                                    prio_options = ["🔥 High", "⚡ Medium", "🧊 Low"]
                                    try: prio_idx = prio_options.index(row['priority'])
                                    except: prio_idx = 1
                                    new_prio = c8.selectbox("Priority", prio_options, index=prio_idx)
                                    
                                    new_assign = None
                                    if is_manager:
                                        all_users = get_active_users()
                                        curr_assign = row['assigned_to'] if row['assigned_to'] else "Unassigned"
                                        assign_opts = ["Unassigned"] + all_users
                                        try: def_idx = assign_opts.index(curr_assign)
                                        except: def_idx = 0
                                        new_assign_sel = c9.selectbox("Reassign To", assign_opts, index=def_idx)
                                        new_assign = new_assign_sel if new_assign_sel != "Unassigned" else None
                                    else:
                                        c9.text_input("Assigned To", value=row['assigned_to'], disabled=True)

                                    b1, b2 = st.columns(2)
                                    if b1.form_submit_button("💾 Save Changes"):
                                        # Use fallback if user checked "New" but left empty
                                        final_c = new_coord if new_coord else curr_coord
                                        final_p = new_proj if new_proj else curr_proj
                                        
                                        if update_task_full(row['id'], new_desc, new_date, new_prio, new_rem, new_assign, new_points, new_subject, final_c, final_p, is_manager):
                                            st.toast("✅ Updated!")
                                            time.sleep(0.5)
                                            st.rerun()
                                    
                                    if b2.form_submit_button("✅ Mark Completed"):
                                        update_task_status(row['id'], "Completed", new_rem)
                                        st.rerun()

            else: st.info("👋 No active tasks found.")

if __name__ == "__main__":
    main()
