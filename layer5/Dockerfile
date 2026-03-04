FROM python:3.11-slim
WORKDIR /app
COPY tracker/requirements.txt .
RUN pip install -r requirements.txt
COPY tracker/ .
CMD ["python", "main.py"]
