# Railway (or any Docker host): avoid Railpack build-plan issues by building with Docker
FROM python:3.11-slim

WORKDIR /app

# Install project and dependencies
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir -e .

# Railway sets PORT; app reads it via os.getenv("PORT", "5000")
ENV HOST=0.0.0.0
EXPOSE 5000

CMD ["hunter", "webhook"]
