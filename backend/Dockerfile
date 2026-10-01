FROM python:3.14-slim-trixie
WORKDIR /app
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir --upgrade "setuptools >=78.1.1"
COPY --from=ghcr.io/astral-sh/uv:0.12.17 /uv /bin/uv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY . .
ENV PATH="/app/.venv/bin:$PATH"
ENV AWS_DEFAULT_REGION=us-east-2
CMD ["uvicorn", "aircraftmon_server:app", "--host", "0.0.0.0", "--port", "4200"]
