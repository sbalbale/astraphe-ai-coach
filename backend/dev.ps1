$ErrorActionPreference = "Stop"

# Start backend with timestamped logs (including access logs)
uvicorn app.main:app --reload --port 8000 --log-config ".\\uvicorn-log-config.json"

