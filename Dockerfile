# Dockerfile for wenjv Backend (Draft)
FROM python:3.11-slim

WORKDIR /app

# Install system build dependencies, init system (tini), and clean up cache
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    tini \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create non-root user for production security best practices
RUN useradd -m -u 1000 appuser && \
    mkdir -p /home/appuser/.config/wenjv && \
    chown -R appuser:appuser /app /home/appuser

USER appuser

# Copy application source code
COPY --chown=appuser:appuser . .

EXPOSE 8000

# Use tini as lightweight init system to handle PID 1 signals and graceful shutdowns
ENTRYPOINT ["/usr/bin/tini", "--"]

# Start FastAPI server with proxy headers support
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
