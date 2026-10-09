import streamlit as st
import pandas as pd
import libsql_client
from datetime import date
import smtplib
from email.mime.text import MIMEText

st.set_page_config(page_title="Life Logger", layout="wide")

# --- 1. Database Setup ---
@st.cache_resource
def get_db():
    url = st.secrets["TURSO_DATABASE_URL"]
    token = st.secrets["TURSO_AUTH_TOKEN"]
    return libsql_client.create_client_sync(url=url, auth_token=token)

client = get_db()

# Create table
client.execute("""
    CREATE TABLE IF NOT EXISTS life_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
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

# Check and upgrade existing table if missing the new columns
existing_cols = [col[1] for col in client.execute("PRAGMA table_info(life_logs)").rows]
if "due_date" not in existing_cols:
    client.execute("ALTER TABLE life_logs ADD COLUMN due_date DATE")
    client.execute("ALTER TABLE life_logs ADD COLUMN is_done INTEGER DEFAULT 0")
    client.execute("ALTER TABLE life_logs ADD COLUMN done_date DATE")

# --- 2. Email Notification Function ---
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

# --- 3. UI Layout ---
st.title("📓 Daily Life Logger")

tab1, tab2, tab3 = st.tabs(["📝 Dashboard & Log Entry", "🔍 Search & Filter", "⏰ Reminders"])

# DEFAULT CATEGORIES
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
                
                # If there's no due date, it's essentially "Done" immediately at the time of logging.
                # If there is a due date, it starts as pending (is_done = 0).
                is_done_val = 0 if set_due else 1
                done_date_val = str(log_date) if not set_due else ""
                
                client.execute(
                    """INSERT INTO life_logs 
                       (log_date, category, title, details, due_date, is_done, done_date, reminder_date) 
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    [str(log_date), category, title, details, due_date_str, is_done_val, done_date_val, rem_date_str]
                )
                st.success("Log saved successfully!")
                st.rerun()

    st.subheader("Action Dashboard")
    st.write("Manage your upcoming tasks and past entries.")
    
    # Sort logic: Pending first, then by Due Date (closest/overdue first), then Logs without Due Dates, then Completed
    result = client.execute("""
        SELECT id, is_done, log_date, due_date, done_date, category, title, details 
        FROM life_logs 
        ORDER BY 
            is_done ASC, 
            CASE WHEN due_date = '' OR due_date IS NULL THEN 1 ELSE 0 END ASC,
            due_date ASC, 
            log_date DESC
        LIMIT 50
    """)
    
    if result.rows:
        df = pd.DataFrame(result.rows, columns=["ID", "Done", "Logged", "Due Date", "Finished On", "Category", "Title", "Details"])
        
        # Convert sqlite integers back to booleans
        df["Done"] = df["Done"].astype(bool)
        
        # Insert an explicit Delete column at the very beginning (index 0) for mobile taps
        df.insert(0, "Delete", False)
        
        today = date.today()
        df['temp_due'] = pd.to_datetime(df['Due Date']).dt.date
        
        def highlight_due_status(row):
            is_done = row['Done']
            due_date_val = row['temp_due']
            
            # If it's done, leave it plain
            if is_done:
                return [''] * len(row)
            
            # If it's pending and past due, color it light pink
            if pd.notna(due_date_val) and due_date_val < today:
                return ['background-color: #FFD1DC; color: black'] * len(row)
                
            return [''] * len(row)
            
        styled_df = df.style.apply(highlight_due_status, axis=1)
        
        edited_df = st.data_editor(
            styled_df,
            column_config={
                "ID": None, # Hide ID
                "temp_due": None, # Hide the helper column
                "Delete": st.column_config.CheckboxColumn("🗑️ Delete", default=False),
                "Done": st.column_config.CheckboxColumn("Done?", default=False),
                "Logged": st.column_config.TextColumn(disabled=True),
                "Due Date": st.column_config.TextColumn(disabled=True),
                "Finished On": st.column_config.TextColumn(disabled=True),
                "Category": st.column_config.TextColumn(disabled=True),
                "Title": st.column_config.TextColumn(disabled=True),
                "Details": st.column_config.TextColumn(disabled=True)
            },
            use_container_width=True,
            hide_index=True,
            key="dashboard_editor"
        )
        
        # Detect if a Delete checkbox was checked
        if edited_df["Delete"].any():
            deletions = edited_df[edited_df["Delete"] == True]
            for del_id in deletions["ID"]:
                client.execute("DELETE FROM life_logs WHERE id = ?", [int(del_id)])
            st.rerun()
            
        # Detect if a Done checkbox was changed
        elif not edited_df["Done"].equals(df["Done"]):
            updates_made = False
            for i, row in edited_df.iterrows():
                row_id = row["ID"]
                original_done = df.loc[i, "Done"]
                new_done = row["Done"]
                
                if not original_done and new_done:
                    client.execute(
                        "UPDATE life_logs SET is_done = 1, done_date = ? WHERE id = ?",
                        [str(today), row_id]
                    )
                    updates_made = True
                    
                elif original_done and not new_done:
                    client.execute(
                        "UPDATE life_logs SET is_done = 0, done_date = '' WHERE id = ?",
                        [row_id]
                    )
                    updates_made = True

            if updates_made:
                st.rerun()
    else:
        st.info("Your dashboard is empty.")

with tab2:
    st.subheader("Effortless Search")
    st.write("Search all past entries.")
    
    result = client.execute("SELECT id, log_date, due_date, done_date, category, title, details FROM life_logs ORDER BY log_date DESC")
    
    if result.rows:
        df = pd.DataFrame(result.rows, columns=["ID", "Logged", "Due", "Finished", "Category", "Title", "Details"])
        df['Logged'] = pd.to_datetime(df['Logged']).dt.date
        
        f_col1, f_col2, f_col3 = st.columns([1, 1, 2])
        with f_col1:
            cat_filter = st.multiselect("Filter by Category", categories)
        with f_col2:
            date_filter = st.date_input("Date Range", value=(), key="dr")
        with f_col3:
            search_text = st.text_input("🔍 Search keyword (searches titles and notes)")

        filtered_df = df.copy()
        
        if cat_filter:
            filtered_df = filtered_df[filtered_df['Category'].isin(cat_filter)]
            
        if len(date_filter) == 2:
            start_d, end_d = date_filter
            filtered_df = filtered_df[(filtered_df['Logged'] >= start_d) & (filtered_df['Logged'] <= end_d)]
            
        if search_text:
            mask = filtered_df['Title'].str.contains(search_text, case=False, na=False) | \
                   filtered_df['Details'].str.contains(search_text, case=False, na=False)
            filtered_df = filtered_df[mask]

        # Insert an explicit Delete column at the very beginning (index 0)
        filtered_df.insert(0, "Delete", False)

        edited_search_df = st.data_editor(
            filtered_df,
            column_config={
                "ID": None,
                "Delete": st.column_config.CheckboxColumn("🗑️ Delete", default=False),
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
        
        # Detect if a Delete checkbox was checked in the Search results
        if edited_search_df["Delete"].any():
            deletions = edited_search_df[edited_search_df["Delete"] == True]
            for del_id in deletions["ID"]:
                client.execute("DELETE FROM life_logs WHERE id = ?", [int(del_id)])
            st.rerun()

    else:
        st.info("No logs found. Start typing in the Log Entry tab!")

with tab3:
    st.subheader("Upcoming Reminders")
    
    today_str = str(date.today())
    reminders = client.execute(
        "SELECT id, title, reminder_date FROM life_logs WHERE reminder_date != '' AND reminder_sent = 0 ORDER BY reminder_date ASC"
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
                            client.execute("UPDATE life_logs SET reminder_sent = 1 WHERE id = ?", [row_id])
                            sent_count += 1
                            
                if sent_count > 0:
                    st.success(f"Successfully dispatched {sent_count} email(s)!")
                    st.rerun()
                else:
                    st.info("No reminders are currently due for today.")
    else:
        st.success("All caught up! No pending reminders.")