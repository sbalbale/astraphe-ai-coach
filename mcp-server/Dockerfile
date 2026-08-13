# Build from the REPO ROOT, not this directory — this image needs both backend/app and
# mcp-server/astraphe_mcp (see docs/MCP_SERVER.md's reuse strategy):
#   docker build -f mcp-server/Dockerfile -t astraphe-mcp .
FROM python:3.12-slim

WORKDIR /app

# Needed for some of backend/requirements.txt's math libraries (numpy/pandas), same as
# backend/Dockerfile.
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy only requirements first to leverage Docker layer caching.
COPY backend/requirements.txt backend-requirements.txt
COPY mcp-server/requirements.txt mcp-requirements.txt
RUN pip install --no-cache-dir -r backend-requirements.txt -r mcp-requirements.txt

# Only the pieces this service actually needs from backend/ — not the FastAPI app itself.
COPY backend/app ./backend/app
COPY mcp-server/astraphe_mcp ./mcp-server/astraphe_mcp

ENV PYTHONPATH=/app/backend:/app/mcp-server

EXPOSE 8090

CMD ["uvicorn", "astraphe_mcp.asgi:app", "--host", "0.0.0.0", "--port", "8090"]
