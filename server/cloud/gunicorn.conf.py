import os

bind = "0.0.0.0:" + os.environ.get("PORT", "8080")
workers = 2
worker_class = "gthread"
threads = 4
timeout = 150
graceful_timeout = 120
max_requests = 500
max_requests_jitter = 50
accesslog = None
errorlog = "-"
limit_request_line = 4094
limit_request_fields = 32
limit_request_field_size = 4094


def post_worker_init(worker):
    # Each worker may sweep; the common admission lock makes it safe.
    import logging
    import threading
    from django.db import connections
    from cloud.service.maintenance import maintain

    def sweep():
        while worker.alive:
            try:
                maintain()
            except Exception:
                logging.getLogger("gunicorn.error").error("Account maintenance failed")
            finally:
                connections.close_all()
            if threading.Event().wait(60):
                return

    threading.Thread(target=sweep, name="account-maintenance", daemon=True).start()
