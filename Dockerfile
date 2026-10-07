FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv/app
RUN apt-get update && apt-get install -y --no-install-recommends libmagic1 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN useradd --create-home appuser
COPY --chown=appuser:appuser app ./app
COPY --chown=appuser:appuser templates ./templates
COPY --chown=appuser:appuser media/dps/default.png ./media/dps/default.png
RUN mkdir -p /srv/data && chown -R appuser:appuser /srv/data /srv/app/media
USER appuser
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-8000}"]
