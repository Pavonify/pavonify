# -------- Base builder stage --------
FROM python:3.12-slim AS builder

# Prevent .pyc and force stdout
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install build deps (for compiling wheels only)
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      build-essential \
      gcc \
 && rm -rf /var/lib/apt/lists/*

# Create venv
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Install Python deps into venv
COPY requirements.txt .
RUN pip install --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

# -------- Runtime stage --------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install only the runtime libs you need
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      libstdc++6 \
      libgcc-s1 \
 && rm -rf /var/lib/apt/lists/*

# Copy venv from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Copy only app source (not venv, git, etc. — handled by .dockerignore)
COPY . .

EXPOSE 8080

CMD ["gunicorn", "lang_platform.wsgi:application", "--bind", "0.0.0.0:8080", "--workers", "3"]
