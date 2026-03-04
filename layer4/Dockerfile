FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && \
    apt-get install -y chromium chromium-driver && \
    rm -rf /var/lib/apt/lists/*
COPY poster/requirements.txt .
RUN pip install -r requirements.txt
RUN playwright install chromium
COPY poster/ .
CMD ["python", "main.py"]
