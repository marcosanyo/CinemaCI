FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies including ffmpeg and system libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv and uvx for official mcp-grafana execution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Pre-install mcp-grafana tool cache during image build to avoid runtime network download
RUN uv tool install mcp-grafana

# Copy requirements first (for layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Ensure storage and scratch directories exist
RUN mkdir -p storage /tmp/cinema-ci

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
