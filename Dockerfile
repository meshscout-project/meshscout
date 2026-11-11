# syntax=docker/dockerfile:1
FROM python:3.12-slim

# Set environment variables for non-interactive Python execution
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MESHSCOUT_DEM_DIR=/dem \
    MESHSCOUT_CACHE_DIR=/data/cache \
    PATH="/home/meshscout/.local/bin:${PATH}"

# Create non-root system user and group (UID/GID 1000)
RUN groupadd -g 1000 meshscout && \
    useradd -u 1000 -g meshscout -m -s /bin/sh meshscout

# Create application directory and mount points with non-root ownership
WORKDIR /app
RUN mkdir -p /data /dem /app && \
    chown -R meshscout:meshscout /data /dem /app

# Switch to non-root user for package installation and execution
USER meshscout

# Copy application source code
COPY --chown=meshscout:meshscout . /app

# Install package with web extra dependencies
RUN pip install --no-cache-dir --user .[web]

# Create meshscout wrapper script to support 'meshscout web' as an alias for 'meshscout serve'
USER root
RUN printf '#!/bin/sh\nif [ "$1" = "web" ]; then shift; exec /home/meshscout/.local/bin/meshscout serve "$@"; else exec /home/meshscout/.local/bin/meshscout "$@"; fi\n' > /usr/local/bin/meshscout && \
    chmod +x /usr/local/bin/meshscout
USER meshscout

# Persistent volumes for SQLite state and DEM elevation tiles
VOLUME ["/data", "/dem"]

# Expose web workbench port
EXPOSE 8000

# Periodic container healthcheck against status endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/api/status').getcode() == 200 else 1)"

# Entrypoint and default arguments
ENTRYPOINT ["meshscout", "web"]
CMD ["--host", "0.0.0.0", "--port", "8000", "--db-path", "/data/mesh_state.db"]
