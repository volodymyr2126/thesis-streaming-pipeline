FROM python:3.11-slim

WORKDIR /app
COPY scripts/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY scripts/config.py .
COPY scripts/historical_loader.py .

CMD ["python", "-u", "historical_loader.py"]
