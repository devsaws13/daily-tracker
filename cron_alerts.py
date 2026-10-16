import os
import urllib.request
from datetime import date
import libsql_client

def send_ntfy_reminder(topic, title, message):
    if not topic:
        return False
    try:
        req = urllib.request.Request(
            f"https://ntfy.sh/{topic}",
            data=message.encode('utf-8'),
            headers={
                "Title": title.encode('utf-8'),
                "Tags": "rotating_light,clipboard"
            }
        )
        urllib.request.urlopen(req)
        return True
    except Exception as e:
        print(f"Failed to send NTFY to {topic}: {e}")
        return False

def run_job():
    url = os.environ.get("TURSO_DATABASE_URL")
    token = os.environ.get("TURSO_AUTH_TOKEN")
    
    if not url or not token:
        print("Missing database credentials.")
        return

    client = libsql_client.create_client_sync(url=url, auth_token=token)
    today_str = str(date.today())

    # Get all users with valid NTFY topics
    users = client.execute("SELECT username, ntfy_topic FROM users WHERE ntfy_topic != ''").rows
    
    total_sent = 0
    for user_row in users:
        username, topic = user_row[0], user_row[1]
        
        # Get pending due tasks for this user
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
                
    print(f"Cron Job Finished. Dispatched {total_sent} alerts across {len(users)} user(s).")

if __name__ == "__main__":
    run_job()
