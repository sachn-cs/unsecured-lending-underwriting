FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md /app/
COPY ulu /app/ulu
COPY demo.py /app/demo.py

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -e ".[api]"

EXPOSE 8000

CMD ["uvicorn", "ulu.api:app", "--host", "0.0.0.0", "--port", "8000"]
