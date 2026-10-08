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

client.execute("""
    CREATE TABLE IF NOT EXISTS life_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        log_date DATE,
        category TEXT,
        title TEXT,
        details TEXT,
        reminder_date DATE,
        reminder_sent INTEGER DEFAULT 0
    )
""")

# --- 2. Email Notification Function ---
def send_email_reminder(to_email, subject, body):
    try:
        sender = st.secrets["SMTP_EMAIL"]
        password = st.secrets["SMTP_PASSWORD"]
        
        msg = MIMEText(body)
        msg['Subject'] = subject
        msg['From'] = sender
        msg['To'] = to_email

        # Using Gmail SMTP as standard
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(sender, password)
            server.send_message(msg)
        return True
    except Exception as e:
        st.error(f"Failed to send email: {e}")
        return False

# --- 3. UI Layout ---
st.title("📓 Daily Life Logger")

tab1, tab2, tab3 = st.tabs(["📝 Log Entry", "🔍 Search & Filter", "⏰ Reminders"])

# DEFAULT CATEGORIES
categories = ["🚗 Vehicle", "💊 Health & Medical", "✈️ Travel", "💼 Work", "🏠 Home", "🌱 Other"]

with tab1:
    with st.container(border=True):
        col1, col2 = st.columns(2)
        
        with col1:
            log_date = st.date_input("Date", value=date.today())
            category = st.selectbox("Category", categories)
            title = st.text_input("Title", placeholder="e.g., Wagon R CNG Service, Dental checkup, Train to Rajkot")
            
        with col2:
            details = st.text_area("Details & Notes", placeholder="Mechanic details, medicine dosage, booking PNR...")
            set_reminder = st.checkbox("Set a future reminder?")
            reminder_date = st.date_input("Reminder Date", value=date.today()) if set_reminder else None

        if st.button("Save Log", type="primary", use_container_width=True):
            if not title:
                st.warning("Title is required.")
            else:
                rem_date_str = str(reminder_date) if set_reminder else ""
                client.execute(
                    "INSERT INTO life_logs (log_date, category, title, details, reminder_date) VALUES (?, ?, ?, ?, ?)",
                    [str(log_date), category, title, details, rem_date_str]
                )
                st.success("Log saved successfully!")
                st.rerun()

with tab2:
    st.subheader("Effortless Search")
    
    # Fetch all logs
    result = client.execute("SELECT id, log_date, category, title, details, reminder_date FROM life_logs ORDER BY log_date DESC")
    
    if result.rows:
        df = pd.DataFrame(result.rows, columns=["ID", "Date", "Category", "Title", "Details", "Reminder Date"])
        df['Date'] = pd.to_datetime(df['Date']).dt.date
        
        # Filter Layout
        f_col1, f_col2, f_col3 = st.columns([1, 1, 2])
        with f_col1:
            cat_filter = st.multiselect("Filter by Category", categories)
        with f_col2:
            date_filter = st.date_input("Date Range", value=(), key="dr")
        with f_col3:
            search_text = st.text_input("🔍 Search keyword (searches titles and notes)")

        # Apply Pandas filtering logic dynamically
        filtered_df = df.copy()
        
        if cat_filter:
            filtered_df = filtered_df[filtered_df['Category'].isin(cat_filter)]
            
        if len(date_filter) == 2:
            start_d, end_d = date_filter
            filtered_df = filtered_df[(filtered_df['Date'] >= start_d) & (filtered_df['Date'] <= end_d)]
            
        if search_text:
            # Case-insensitive search across both Title and Details columns
            mask = filtered_df['Title'].str.contains(search_text, case=False, na=False) | \
                   filtered_df['Details'].str.contains(search_text, case=False, na=False)
            filtered_df = filtered_df[mask]

        st.dataframe(
            filtered_df.drop(columns=["ID"]), 
            use_container_width=True, 
            hide_index=True
        )
    else:
        st.info("No logs found. Start typing in the Log Entry tab!")

with tab3:
    st.subheader("Upcoming Reminders")
    
    today_str = str(date.today())
    # Fetch active reminders that haven't been sent yet
    reminders = client.execute(
        "SELECT id, title, reminder_date FROM life_logs WHERE reminder_date != '' AND reminder_sent = 0 ORDER BY reminder_date ASC"
    ).rows
    
    if reminders:
        rem_df = pd.DataFrame(reminders, columns=["ID", "Task", "Due Date"])
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
                    
                    # Only send if the reminder date is today or has passed
                    if due_date <= today_str:
                        subject = f"Reminder: {task_title}"
                        body = f"This is an automated reminder for your logged task: {task_title} due on {due_date}."
                        
                        if send_email_reminder(target_email, subject, body):
                            # Mark as sent in DB so it doesn't send again
                            client.execute("UPDATE life_logs SET reminder_sent = 1 WHERE id = ?", [row_id])
                            sent_count += 1
                            
                if sent_count > 0:
                    st.success(f"Successfully dispatched {sent_count} email(s)!")
                    st.rerun()
                else:
                    st.info("No reminders are currently due for today.")
    else:
        st.success("All caught up! No pending reminders.")