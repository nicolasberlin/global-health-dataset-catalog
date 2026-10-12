FROM mcr.microsoft.com/playwright:v1.63.0-noble
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends python3 nftables util-linux \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 renderer && useradd --uid 10001 --gid 10001 renderer
COPY browser/package.json browser/package-lock.json /app/
RUN npm ci --omit=dev --ignore-scripts
COPY collector /app/collector
COPY browser /app/browser
ENV PYTHONPATH=/app NODE_PATH=/app/node_modules PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    BROWSER_PROXY_URL=http://127.0.0.1:8899 BROWSER_BIND=0.0.0.0
EXPOSE 8002
ENTRYPOINT ["python3", "/app/browser/container_entrypoint.py"]
