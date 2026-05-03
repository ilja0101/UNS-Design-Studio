FROM python:3.11-slim

WORKDIR /app

LABEL org.opencontainers.image.title="UNS Design Studio" \
      org.opencontainers.image.description="Self-contained Unified Namespace simulator for industrial IoT demos, training and development" \
      org.opencontainers.image.source="https://github.com/Ilja0101/UNS-Design-Studio" \
      org.opencontainers.image.licenses="MIT"

# Install dependencies (own layer for cache efficiency)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

# Strip Windows CRLF line endings and make executable
RUN sed -i 's/\r//' /app/entrypoint.sh && chmod +x /app/entrypoint.sh

# /data is the persistent volume mount point for runtime config files
VOLUME /data

# OPC-UA  |  Anomaly TCP  |  Flask dashboard
EXPOSE 4840 9999 5000

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/api/status', timeout=5).read()" || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python", "app.py"]
