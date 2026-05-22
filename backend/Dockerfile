# Use the official Python 3.12 slim image for a small footprint
FROM python:3.12-slim

# Set the working directory
WORKDIR /app

# Install system dependencies (needed for some Python math libraries)
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy only requirements first to leverage Docker cache
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Expose the port FastAPI will run on
EXPOSE 8000

# Command to run the application using uvicorn
# We use 0.0.0.0 to allow the container to accept external traffic
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]