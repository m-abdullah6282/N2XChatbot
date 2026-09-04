import sqlite3
conn = sqlite3.connect('chatbot.db')
conn.row_factory = sqlite3.Row
print("=== SUBSCRIPTIONS (count per admin) ===")
for r in conn.execute("SELECT admin_id, COUNT(*) c, SUM(CASE WHEN status='active' THEN 1 ELSE 0 END) act FROM subscriptions GROUP BY admin_id").fetchall():
    print(dict(r))
print("=== MESSAGES still present ===")
print(conn.execute("SELECT COUNT(*) c FROM messages").fetchone()['c'])
print("=== ADMIN USERS ===")
for r in conn.execute("SELECT id, username, role FROM admin_users").fetchall():
    print(dict(r))
print("=== AGENTS ===")
for r in conn.execute("SELECT id, name, owner_admin_id, primary_color FROM agents").fetchall():
    print(dict(r))
conn.close()
