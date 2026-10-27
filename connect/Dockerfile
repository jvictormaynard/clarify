# Same Python base tag as server/Dockerfile. It is not a digest-pinned image.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN groupadd --gid 10001 relay && useradd --uid 10001 --gid 10001 --no-create-home relay
WORKDIR /app
COPY requirements-lock-linux.txt /app/requirements-lock-linux.txt
COPY connect/requirements.txt /app/connect/requirements.txt
RUN pip install --no-cache-dir -r connect/requirements.txt
COPY computer_relay_protocol.py computer_relay_server.py /app/
USER 10001:10001
EXPOSE 8443
ENTRYPOINT ["python", "computer_relay_server.py"]
