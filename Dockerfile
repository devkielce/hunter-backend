# Railway (or any Docker host): avoid Railpack build-plan issues by building with Docker
FROM python:3.11-slim

WORKDIR /app

# Install project and dependencies
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir -e .

# Railway sets PORT; app reads it via os.getenv("PORT", "5000")
ENV HOST=0.0.0.0
ENV PYTHONUNBUFFERED=1

RUN pip install --no-cache-dir gunicorn

EXPOSE 5000

CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT:-5000} --workers 1 --threads 4 --timeout 120 --access-logfile - --error-logfile - --capture-output --log-level debug hunter.webhook_server:app"]
