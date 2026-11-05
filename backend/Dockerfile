FROM python:3.12-slim
RUN apt-get update && apt-get install -y --only-upgrade apt libapt-pkg7.0 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
RUN useradd --create-home --uid 10001 appuser
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY --chown=appuser:appuser . .
USER appuser
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
