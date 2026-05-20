FROM python:3.11-slim

ENV PIP_DEFAULT_TIMEOUT=180 \
    PIP_RETRIES=10

WORKDIR /app

COPY pyproject.toml README.md ./
COPY app ./app
COPY sample_data ./sample_data

RUN pip install --no-cache-dir .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
