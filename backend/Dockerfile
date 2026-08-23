FROM python:3.14-slim-trixie
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV AWS_DEFAULT_REGION=us-east-2
CMD ["uvicorn", "aircraftmon_server:app", "--host", "0.0.0.0", "--port", "4200"]