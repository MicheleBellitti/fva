FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir "burr[start]"
EXPOSE 7241
CMD ["burr", "--host", "0.0.0.0", "--port", "7241", "--no-open"]
