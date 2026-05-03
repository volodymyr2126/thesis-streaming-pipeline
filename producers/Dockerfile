FROM python:3.11-slim
WORKDIR /app
COPY producers/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY producers/ ./producers/
EXPOSE 8000
CMD ["uvicorn", "producers.src.main:app", "--host", "0.0.0.0", "--port", "8000"]
