import sqlite3
conn = sqlite3.connect('database/sentineledge.db')
conn.execute("UPDATE alerts SET acknowledged=1, acknowledged_by='cleanup' WHERE acknowledged=0")
conn.commit()
rows = conn.execute("SELECT COUNT(*) FROM alerts WHERE acknowledged=0").fetchone()[0]
print("Pending alerts remaining:", rows)
conn.close()