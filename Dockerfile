FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src
COPY prompts ./prompts
COPY schemas ./schemas

RUN python -m pip install --upgrade pip && \
    pip install -e ".[api]"

EXPOSE 8000

CMD ["uvicorn", "interview_lab.api:app", "--host", "0.0.0.0", "--port", "8000"]
