FROM python:3.11-slim

WORKDIR /app

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

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python", "app.py"]
