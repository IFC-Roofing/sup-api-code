FROM python:3.11-slim

WORKDIR /app

# Install system deps for WeasyPrint PDF rendering (NOT wkhtmltopdf)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgobject-2.0-0 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libcairo2 \
    libgdk-pixbuf-2.0-0 \
    libffi-dev \
    libxml2 \
    libxslt1.1 \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for Docker layer caching
COPY tools/sup-api/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Install pipeline deps (pdf-generator uses WeasyPrint, anthropic, etc.)
COPY tools/pdf-generator/requirements.txt /tmp/pipeline-requirements.txt
RUN pip install --no-cache-dir -r /tmp/pipeline-requirements.txt || true

# Copy workspace (in production, mount or COPY only what's needed)
COPY . /workspace

COPY tools/sup-api/ /app/

ENV SUP_WORKSPACE=/workspace
ENV SUP_PORT=8090

# Production: no --reload, workers for concurrency
EXPOSE 8090
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8090", "--workers", "2"]
