"""
Simple database viewer - no extra software needed.
Run with: python show_database.py

Prints every table in the SmartBill database and its rows, so you can
show/prove your data (including the encrypted phone/email columns)
straight from the Command Prompt or VS Code's built-in terminal.
"""
import sqlite3
import os

DB_PATH = os.path.join("instance", "smartbill.db")

if not os.path.exists(DB_PATH):
    print(f"Could not find {DB_PATH}")
    print("Make sure you run this from inside the smartbill folder,")
    print("and that you've run the app at least once (so the database exists).")
    exit()

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# Get all table names
cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
tables = [row["name"] for row in cur.fetchall()]

print("=" * 70)
print(f"SMARTBILL DATABASE  —  {len(tables)} tables found")
print("=" * 70)

for table in tables:
    cur.execute(f"SELECT * FROM {table}")
    rows = cur.fetchall()
    print(f"\n--- TABLE: {table}  ({len(rows)} rows) ---")
    if not rows:
        print("  (empty)")
        continue
    col_names = rows[0].keys()
    print("  " + " | ".join(col_names))
    for row in rows:
        print("  " + " | ".join(str(row[c]) for c in col_names))

conn.close()
print("\n" + "=" * 70)
print("Done. Notice: 'email' and 'phone' columns show scrambled text —")
print("that's encryption at rest. The website decrypts them only when")
print("a logged-in user views their own profile.")
print("=" * 70)
