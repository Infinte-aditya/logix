FROM python:3.11-slim

RUN useradd --create-home appuser

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY app /app/app

USER appuser

CMD ["python", "-m", "app.main"]
