# Bot V3 — Production Docker Image
# FastAPI Control Plane + Event-Driven Workers

FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gcc \
    g++ \
    make \
    libssl-dev \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .
COPY requirements-prod.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt -r requirements-prod.txt

# Copy application code
COPY src/ ./src/
COPY config/ ./config/
COPY main_v3.py .

# Create non-root user for security
RUN useradd -m -u 1000 botuser && chown -R botuser:botuser /app
USER botuser

# Expose ports
EXPOSE 8000 9090

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run FastAPI app with uvicorn (production mode)
CMD ["uvicorn", "main_v3:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
