import os
import socket
import time
import subprocess
import sys

def wait_for_db():
    host = os.environ.get("APS_DB_HOST", "db")
    port = int(os.environ.get("APS_DB_PORT", 5432))
    print(f"Waiting for database at {host}:{port}...")
    while True:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1)
            s.connect((host, port))
            s.close()
            print("Database is ready!")
            break
        except socket.error:
            print("Database not ready, waiting...")
            time.sleep(2)

def main():
    wait_for_db()
    
    # Initialize database schema & seed master data
    print("Initializing database schema & seeding master data...")
    init_cmd = [sys.executable, "main.py", "--init-db", "--save-db"]
    try:
        subprocess.run(init_cmd, check=True)
        print("Database initialized successfully!")
    except subprocess.CalledProcessError as e:
        print(f"Error during database initialization: {e}")
        # We don't fail the whole startup if DB was already partially initialized or has data
    
    # Start FastAPI server
    print("Starting FastAPI server...")
    server_cmd = ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
    os.execvp(server_cmd[0], server_cmd)

if __name__ == "__main__":
    main()
