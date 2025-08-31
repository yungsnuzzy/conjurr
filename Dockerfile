# Use Python 3.11 slim image as base
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV FLASK_APP=app.py
ENV FLASK_ENV=production

# Set work directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create non-root user for security
# Use custom PGID/PUID if specified, otherwise use defaults
RUN if [ -n "$PGID" ] && [ -n "$PUID" ]; then \
        groupadd -g $PGID app && \
        useradd --create-home --shell /bin/bash -u $PUID -g $PGID app; \
    elif [ -n "$PUID" ]; then \
        useradd --create-home --shell /bin/bash -u $PUID app; \
    elif [ -n "$PGID" ]; then \
        groupadd -g $PGID app && \
        useradd --create-home --shell /bin/bash -g $PGID app; \
    else \
        useradd --create-home --shell /bin/bash app; \
    fi && \
    chown -R app:app /app
USER app

# Expose port
EXPOSE 2665

# Health check
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:2665/ || exit 1

# Run the application
CMD ["python", "app.py"]
