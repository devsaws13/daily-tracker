import streamlit as st
import pandas as pd
import libsql_client
from datetime import date
import smtplib
from email.mime.text import MIMEText
import hashlib

st.set_page_config(page_title="Life Logger", layout="wide")

# --- 1. Database Setup ---
def get_db():
    url = st.secrets["TURSO_DATABASE_URL"]
    token = st.secrets["TURSO_AUTH_TOKEN"]
    return libsql_client.create_client_sync(url=url, auth_token=token)

client = get_db()

client.execute("""
    CREATE TABLE IF NOT EXISTS users (
        username TEXT PRIMARY KEY,
        password_hash TEXT
    )
""")

client.execute("""
    CREATE TABLE IF NOT EXISTS life_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        log_date DATE,
        category TEXT,
        title TEXT,
        details TEXT,
        due_date DATE,
        is_done INTEGER DEFAULT 0,
        done_date DATE,
        reminder_date DATE,
        reminder_sent INTEGER DEFAULT 0
    )
""")

existing_cols = [col[1] for col in client.execute("PRAGMA table_info(life_logs)").rows]
if "due_date" not in existing_cols:
    client.execute("ALTER TABLE life_logs ADD COLUMN due_date DATE")
    client.execute("ALTER TABLE life_logs ADD COLUMN is_done INTEGER DEFAULT 0")
    client.execute("ALTER TABLE life_logs ADD COLUMN done_date DATE")
if "username" not in existing_cols:
    client.execute("ALTER TABLE life_logs ADD COLUMN username TEXT DEFAULT 'admin'")

# --- 2. Helper Functions ---
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def send_email_reminder(to_email, subject, body):
    try:
        sender = st.secrets["SMTP_EMAIL"]
        password = st.secrets["SMTP_PASSWORD"]
        msg = MIMEText(body)
        msg['Subject'] = subject
        msg['From'] = sender
        msg['To'] = to_email

        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(sender, password)
            server.send_message(msg)
        return True
    except Exception as e:
        st.error(f"Failed to send email: {e}")
        return False

# --- 3. Authentication Gatekeeper ---
if 'logged_in_user' not in st.session_state:
    st.title("Welcome to Life Logger 📓")
    st.write("Please log in or create an account to access your personal dashboard.")
    
    login_tab, register_tab = st.tabs(["🔒 Log In", "📝 Create Account"])
    
    with login_tab:
        user_input = st.text_input("Username", key="login_user")
        pass_input = st.text_input("Password", type="password", key="login_pass")
        if st.button("Log In", type="primary"):
            if user_input and pass_input:
                hashed_input = hash_password(pass_input)
                result = client.execute("SELECT username FROM users WHERE username = ? AND password_hash = ?", [user_input, hashed_input])
                if result.rows:
                    st.session_state['logged_in_user'] = user_input
                    st.rerun()
                else:
                    st.error("Invalid username or password.")
            else:
                st.warning("Please enter both username and password.")
                
    with register_tab:
        new_user = st.text_input("New Username", key="reg_user")
        new_pass = st.text_input("New Password", type="password", key="reg_pass")
        if st.button("Register"):
            if new_user and new_pass:
                hashed_new = hash_password(new_pass)
                try:
                    client.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", [new_user, hashed_new])
                    st.success("Account created successfully! You can now log in.")
                except:
                    st.error("That username is already taken. Please choose another one.")
            else:
                st.warning("Please fill out all fields.")

# --- 4. Main Application UI ---
else:
    current_user = st.session_state['logged_in_user']
    
    col_header, col_logout = st.columns([8, 1])
    with col_header:
        st.title(f"📓 {current_user}'s Daily Logger")
    with col_logout:
        st.write("") 
        if st.button("Log Out"):
            del st.session_state['logged_in_user']
            st.rerun()

    tab1, tab2, tab3 = st.tabs(["📝 Dashboard & Log Entry", "🔍 Search & Filter", "⏰ Reminders"])
    categories = ["🚗 Vehicle", "💊 Health & Medical", "✈️ Travel", "💼 Work", "🏠 Home", "🌱 Other"]

    with tab1:
        with st.expander("➕ Create New Log", expanded=True):
            col1, col2 = st.columns(2)
            with col1:
                log_date = st.date_input("Entry Date", value=date.today())
                category = st.selectbox("Category", categories)
                title = st.text_input("Title", placeholder="e.g., Wagon R CNG Service, Dental checkup...")
            with col2:
                details = st.text_area("Details & Notes", placeholder="Mechanic details, medicine dosage, booking PNR...", height=115)
            
            st.divider()
            st.write("📅 **Optional Scheduling**")
            scol1, scol2 = st.columns(2)
            with scol1:
                set_due = st.checkbox("Set a Due Date?")
                due_date = st.date_input("Due Date", value=date.today()) if set_due else None
            with scol2:
                set_reminder = st.checkbox("Set an Email Reminder?")
                reminder_date = st.date_input("Reminder Date", value=date.today()) if set_reminder else None

            if st.button("Save Log", type="primary", use_container_width=True):
                if not title:
                    st.warning("Title is required.")
                else:
                    due_date_str = str(due_date) if set_due else ""
                    rem_date_str = str(reminder_date) if set_reminder else ""
                    is_done_val = 0 if set_due else 1
                    done_date_val = str(log_date) if not set_due else ""
                    
                    client.execute(
                        """INSERT INTO life_logs 
                           (username, log_date, category, title, details, due_date, is_done, done_date, reminder_date) 
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        [current_user, str(log_date), category, title, details, due_date_str, is_done_val, done_date_val, rem_date_str]
                    )
                    st.success("Log saved successfully!")
                    st.rerun()

        st.subheader("Action Dashboard")
        
        result = client.execute("""
            SELECT id, is_done, log_date, due_date, done_date, category, title, details 
            FROM life_logs 
            WHERE username = ?
            ORDER BY 
                is_done ASC, 
                CASE WHEN due_date = '' OR due_date IS NULL THEN 1 ELSE 0 END ASC,
                due_date ASC, 
                log_date DESC
            LIMIT 50
        """, [current_user])
        
        # ... inside Tab 1 ...
        if result.rows:
            df = pd.DataFrame(result.rows, columns=["ID", "Done", "Logged", "Due Date", "Finished On", "Category", "Title", "Details"])
            df["Done"] = df["Done"].astype(bool)
            df.insert(0, "Select", False)
            
            today = date.today()
            
            # Use errors='coerce' to prevent crashes, and keep them as actual Date objects for the calendar widget
            df['Logged'] = pd.to_datetime(df['Logged'], errors='coerce').dt.date
            df['Due Date'] = pd.to_datetime(df['Due Date'], errors='coerce').dt.date
            df['Finished On'] = pd.to_datetime(df['Finished On'], errors='coerce').dt.date
            df['temp_due'] = df['Due Date']
            
            def highlight_due_status(row):
                is_done = row['Done']
                due_date_val = row['temp_due']
                if is_done: return [''] * len(row)
                if pd.notna(due_date_val) and due_date_val < today: return ['background-color: #FFD1DC; color: black'] * len(row)
                return [''] * len(row)
                
            styled_df = df.style.apply(highlight_due_status, axis=1).hide(axis="index")
            
            col_toggle, col_text = st.columns([1, 3])
            with col_toggle:
                edit_mode = st.toggle("✏️ Enable Edit Mode")
            with col_text:
                st.write("Toggle on to mark tasks as Done, edit text, or delete. Toggle off to sort columns.")

            if not edit_mode:
                # VIEW MODE: Sortable
                st.dataframe(
                    styled_df,
                    column_config={
                        "ID": None, 
                        "temp_due": None, 
                        "Select": None, # Hide delete column in view mode
                        "Done": st.column_config.CheckboxColumn("Done?", disabled=True, width="small"),
                        "Logged": st.column_config.DateColumn("Logged", format="YYYY-MM-DD"),
                        "Due Date": st.column_config.DateColumn("Due Date", format="YYYY-MM-DD"),
                        "Finished On": st.column_config.DateColumn("Finished On", format="YYYY-MM-DD"),
                        "Category": st.column_config.TextColumn("Category"),
                        "Title": st.column_config.TextColumn("Title"),
                        "Details": st.column_config.TextColumn("Details")
                    },
                    use_container_width=True,
                    hide_index=True
                )
            else:
                # EDIT MODE: Interactive Checkboxes and Editable Calendar Cells
                edited_df = st.data_editor(
                    styled_df,
                    column_config={
                        "ID": None, 
                        "temp_due": None, 
                        "Select": st.column_config.CheckboxColumn("🗑️", default=False, width="small"),
                        "Done": st.column_config.CheckboxColumn("Done?", default=False, width="small"),
                        # CHANGED to DateColumn to enable the calendar picker
                        "Logged": st.column_config.DateColumn("Logged", format="YYYY-MM-DD"),
                        "Due Date": st.column_config.DateColumn("Due Date", format="YYYY-MM-DD"),
                        "Finished On": st.column_config.DateColumn("Finished On", format="YYYY-MM-DD", disabled=True),
                        "Category": st.column_config.SelectboxColumn("Category", options=categories),
                        "Title": st.column_config.TextColumn("Title"),
                        "Details": st.column_config.TextColumn("Details")
                    },
                    use_container_width=True,
                    hide_index=True,
                    key="dashboard_editor"
                )
                
                # Detect Changes
                if not edited_df.drop(columns=["Select"]).equals(df.drop(columns=["Select"])):
                    updates_made = False
                    for i, row in edited_df.iterrows():
                        row_id = row["ID"]
                        
                        # 1. Check for "Done" toggles
                        original_done = df.loc[i, "Done"]
                        new_done = row["Done"]
                        if not original_done and new_done:
                            client.execute("UPDATE life_logs SET is_done = 1, done_date = ? WHERE id = ? AND username = ?", [str(today), row_id, current_user])
                            updates_made = True
                        elif original_done and not new_done:
                            client.execute("UPDATE life_logs SET is_done = 0, done_date = '' WHERE id = ? AND username = ?", [row_id, current_user])
                            updates_made = True
                            
                        # 2. Check for inline text/dropdown/calendar edits
                        c_cat = str(row['Category'])
                        c_tit = str(row['Title'])
                        c_det = str(row['Details']) if pd.notna(row['Details']) else ""
                        
                        # Safe parsing for dates coming out of the calendar widget
                        c_due = str(row['Due Date']) if pd.notna(row['Due Date']) else ""
                        c_log = str(row['Logged']) if pd.notna(row['Logged']) else ""
                        
                        # Safe string comparisons against original dataframe objects
                        orig_due = str(df.loc[i, "Due Date"]) if pd.notna(df.loc[i, "Due Date"]) else ""
                        orig_log = str(df.loc[i, "Logged"]) if pd.notna(df.loc[i, "Logged"]) else ""
                        
                        if (str(df.loc[i, "Category"]) != c_cat or 
                            str(df.loc[i, "Title"]) != c_tit or 
                            (str(df.loc[i, "Details"]) if pd.notna(df.loc[i, "Details"]) else "") != c_det or 
                            orig_due != c_due or
                            orig_log != c_log):
                            
                            client.execute(
                                "UPDATE life_logs SET category=?, title=?, details=?, due_date=?, log_date=? WHERE id=? AND username=?",
                                [c_cat, c_tit, c_det, c_due, c_log, int(row_id), current_user]
                            )
                            updates_made = True

                    if updates_made: 
                        st.rerun()

                if edited_df["Select"].any():
                    deletions = edited_df[edited_df["Select"] == True]
                    st.error(f"⚠️ You have selected {len(deletions)} log(s) for deletion. This action cannot be undone.")
                    if st.button("Confirm Deletion", type="primary", key="dash_del_btn"):
                        for del_id in deletions["ID"]:
                            client.execute("DELETE FROM life_logs WHERE id = ? AND username = ?", [int(del_id), current_user])
                        st.rerun()
        else:
            st.info("Your dashboard is empty.")

    with tab2:
        st.subheader("Effortless Search")
        result = client.execute("SELECT id, log_date, due_date, done_date, category, title, details FROM life_logs WHERE username = ? ORDER BY log_date DESC", [current_user])
        
        if result.rows:
            df = pd.DataFrame(result.rows, columns=["ID", "Logged", "Due", "Finished", "Category", "Title", "Details"])
            df['Logged'] = pd.to_datetime(df['Logged']).dt.date
            
            f_col1, f_col2, f_col3 = st.columns([1, 1, 2])
            with f_col1: cat_filter = st.multiselect("Filter by Category", categories)
            with f_col2: date_filter = st.date_input("Date Range", value=(), key="dr")
            with f_col3: search_text = st.text_input("🔍 Search keyword")

            filtered_df = df.copy()
            if cat_filter: filtered_df = filtered_df[filtered_df['Category'].isin(cat_filter)]
            if len(date_filter) == 2:
                start_d, end_d = date_filter
                filtered_df = filtered_df[(filtered_df['Logged'] >= start_d) & (filtered_df['Logged'] <= end_d)]
            if search_text:
                mask = filtered_df['Title'].str.contains(search_text, case=False, na=False) | filtered_df['Details'].str.contains(search_text, case=False, na=False)
                filtered_df = filtered_df[mask]

            display_df = filtered_df.copy()
            display_df.insert(0, "Select", False)
            display_df['Logged'] = pd.to_datetime(display_df['Logged']).dt.strftime('%Y-%m-%d')
            display_df['Due'] = pd.to_datetime(display_df['Due'], errors='coerce').dt.strftime('%Y-%m-%d').fillna('')
            display_df['Finished'] = pd.to_datetime(display_df['Finished'], errors='coerce').dt.strftime('%Y-%m-%d').fillna('')

            edited_search_df = st.data_editor(
                display_df,
                column_config={
                    "ID": None,
                    "Select": st.column_config.CheckboxColumn("🗑️", default=False, width="small"),
                    "Logged": st.column_config.TextColumn(disabled=True),
                    "Due": st.column_config.TextColumn(disabled=True),
                    "Finished": st.column_config.TextColumn(disabled=True),
                    "Category": st.column_config.TextColumn(disabled=True),
                    "Title": st.column_config.TextColumn(disabled=True),
                    "Details": st.column_config.TextColumn(disabled=True)
                },
                use_container_width=True,
                hide_index=True,
                key="search_editor"
            )
            
            if edited_search_df["Select"].any():
                deletions = edited_search_df[edited_search_df["Select"] == True]
                st.error(f"⚠️ You have selected {len(deletions)} log(s) for deletion. This action cannot be undone.")
                if st.button("Confirm Deletion", type="primary", key="search_del_btn"):
                    for del_id in deletions["ID"]:
                        client.execute("DELETE FROM life_logs WHERE id = ? AND username = ?", [int(del_id), current_user])
                    st.rerun()
        else:
            st.info("No logs found. Start typing in the Log Entry tab!")

    with tab3:
        st.subheader("Upcoming Reminders")
        today_str = str(date.today())
        reminders = client.execute(
            "SELECT id, title, reminder_date FROM life_logs WHERE username = ? AND reminder_date != '' AND reminder_sent = 0 ORDER BY reminder_date ASC", [current_user]
        ).rows
        
        if reminders:
            rem_df = pd.DataFrame(reminders, columns=["ID", "Task", "Reminder Scheduled For"])
            st.dataframe(rem_df.drop(columns=["ID"]), use_container_width=True, hide_index=True)
            
            st.divider()
            st.write("📧 **Email Dispatch**")
            target_email = st.text_input("Send reminders to:", placeholder="your.email@gmail.com")
            
            if st.button("Dispatch Due Emails Now"):
                if not target_email:
                    st.error("Please enter a destination email.")
                else:
                    sent_count = 0
                    for row in reminders:
                        row_id, task_title, due_date = row
                        if due_date <= today_str:
                            subject = f"Life Logger Reminder: {task_title}"
                            body = f"This is an automated reminder for your logged task: {task_title}.\nScheduled for: {due_date}."
                            if send_email_reminder(target_email, subject, body):
                                client.execute("UPDATE life_logs SET reminder_sent = 1 WHERE id = ? AND username = ?", [row_id, current_user])
                                sent_count += 1
                    if sent_count > 0:
                        st.success(f"Successfully dispatched {sent_count} email(s)!")
                        st.rerun()
                    else:
                        st.info("No reminders are currently due for today.")
        else:
            st.success("All caught up! No pending reminders.")