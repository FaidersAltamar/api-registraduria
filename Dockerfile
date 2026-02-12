FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

ENV PYTHONUNBUFFERED=1

CMD ["sh", "-c", "while true; do python main.py; echo 'Reiniciando en 5s...'; sleep 5; done"]
