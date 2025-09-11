# -------- Base runtime (Debian slim) --------
FROM python:3.12-slim AS runtime

# Don't write .pyc files, flush stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install the C++ runtime that grpc / google-generativeai needs
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      libstdc++6 \
      libgcc-s1 \
      build-essential \
 && rm -rf /var/lib/apt/lists/*

# Create a virtualenv
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Working directory
WORKDIR /app

# Copy only requirements first
COPY requirements.txt /app/

# Install Python dependencies
RUN pip install --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

# Copy the rest of your app
COPY . /app

# Expose the port Gunicorn will bind to
EXPOSE 8080

# Start Gunicorn (change module path if your project isn’t lang_platform)
CMD ["/opt/venv/bin/gunicorn", "lang_platform.wsgi:application", "--bind", "0.0.0.0:8080", "--workers", "3"]
