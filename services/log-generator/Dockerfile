FROM python:3.11-slim

RUN useradd --create-home appuser

WORKDIR /app

COPY app /app/app

RUN mkdir -p /data && chown appuser:appuser /data

USER appuser

CMD ["python", "-m", "app.main"]