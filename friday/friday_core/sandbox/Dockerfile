# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

FROM python:3.14-slim AS runtime

# ---------------------------------------------------------------
# Dependencies — pinned for reproducibility
# NOTE: frappe-client is not yet published to PyPI (only 0.1.0.dev0
# exists, which drags in ipython + rust toolchain). The container uses
# raw requests for Frappe API calls from skill handlers. Once frappe-
# client v1.0.0 is released, add: frappe-client==1.0.0
# ---------------------------------------------------------------
RUN pip install --no-cache-dir \
    requests==2.32.3

# ---------------------------------------------------------------
# Nonroot user (matches UID 65532 used by runner.py)
# ---------------------------------------------------------------
RUN useradd --no-create-home --uid 65532 friday
USER friday
WORKDIR /home/friday

# ---------------------------------------------------------------
# Entrypoint — reads task JSON from stdin, exits with result
# ---------------------------------------------------------------
COPY --chown=friday:friday entrypoint.py /home/friday/entrypoint.py
COPY --chown=friday:friday handlers.py /home/friday/handlers.py
ENTRYPOINT ["python", "/home/friday/entrypoint.py"]
