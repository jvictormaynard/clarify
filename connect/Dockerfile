# Official Python OCI index verified against Docker Hub on 2026-10-27.
FROM python:3.12-slim@sha256:e70237b264442328526ff29d6b3c43bd8abcf6cbab78a949322fb69b7d91d6b6
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN groupadd --gid 10001 relay && useradd --uid 10001 --gid 10001 --no-create-home relay
WORKDIR /app
COPY requirements-lock-linux.txt /app/requirements-lock-linux.txt
COPY connect/requirements.txt /app/connect/requirements.txt
RUN pip install --no-cache-dir -r connect/requirements.txt
COPY computer_relay_protocol.py computer_relay_server.py /app/
COPY LICENSE /app/LICENSE
USER 10001:10001
EXPOSE 8443
ENTRYPOINT ["python", "computer_relay_server.py"]
