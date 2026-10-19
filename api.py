import os
from flask import Flask, request
import urllib.request
from datetime import date
import libsql_client

app = Flask(__name__)

def send_ntfy_reminder(topic, title, message):
    if not topic: return False
    try:
        req = urllib.request.Request(
            f"https://ntfy.sh/{topic}",
            data=message.encode('utf-8'),
            headers={"Title": title.encode('utf-8'), "Tags": "rotating_light,clipboard"}
        )
        urllib.request.urlopen(req)
        return True
    except Exception as e:
        print(f"Failed to send NTFY to {topic}: {e}")
        return False

@app.route('/dispatch_reminders', methods=['GET'])
def dispatch_reminders():
    secret_key = os.environ.get("CRON_SECRET")
    if request.args.get('key') != secret_key:
        return "Unauthorized", 401

    db_url = os.environ.get("TURSO_DATABASE_URL")
    db_token = os.environ.get("TURSO_AUTH_TOKEN")

    try:
        with libsql_client.create_client_sync(url=db_url, auth_token=db_token) as client:
            today_str = str(date.today())
            users = client.execute("SELECT username, ntfy_topic FROM users WHERE ntfy_topic != ''").rows
            
            total_sent = 0
            for user_row in users:
                username, topic = user_row[0], user_row[1]
                tasks = client.execute("""
                    SELECT title, due_date 
                    FROM life_logs 
                    WHERE username = ? AND is_done = 0 AND due_date != '' AND due_date <= ?
                """, [username, today_str]).rows
                
                for task in tasks:
                    title, due_date = task[0], task[1]
                    message = f"PENDING TASK: {title}\nDue Date: {due_date}"
                    if send_ntfy_reminder(topic, "Life Logger Alert", message):
                        total_sent += 1
                        
            return f"Cron execution successful. Dispatched {total_sent} alerts.", 200
            
    except Exception as e:
        return f"Database Error: {str(e)}", 500