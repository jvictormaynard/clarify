FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 clarify
WORKDIR /app
COPY server/requirements.txt /app/server/requirements.txt
RUN pip install --no-cache-dir --require-hashes -r server/requirements.txt
COPY dictionary_snippets.py /app/dictionary_snippets.py
COPY shared /app/shared
COPY server /app/server
USER clarify
EXPOSE 8080
CMD ["python", "server/start.py"]
