FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*
COPY analyzer/requirements.txt .
RUN pip install -r requirements.txt
COPY analyzer/ .
CMD ["python", "main.py"]
