FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.txt prometheus_client python-snappy protobuf python-dotenv

# Copy application
COPY pyemvue/ ./pyemvue/
COPY grafana_exporter.py ./

# Create non-root user
RUN useradd -m -u 1000 exporter
USER exporter

# Run exporter
CMD ["python", "grafana_exporter.py"]
