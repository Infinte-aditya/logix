FROM python:3.11-slim

RUN useradd --create-home appuser

WORKDIR /app

COPY services/gateway/requirements.txt .
COPY contracts /app/contracts

RUN pip install --no-cache-dir -r requirements.txt

COPY services/gateway/app /app/app

USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]