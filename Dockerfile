# ── Stage 1: Build ──
FROM python:3.12-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    wget gnupg unzip curl xvfb ca-certificates \
    && wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | gpg --dearmor > /usr/share/keyrings/chrome-key.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/chrome-key.gpg] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends google-chrome-stable \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Stage 2: Runtime (slim) ──
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    wget gnupg unzip curl xvfb ca-certificates \
    && wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | gpg --dearmor > /usr/share/keyrings/chrome-key.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/chrome-key.gpg] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends google-chrome-stable \
    && rm -rf /var/lib/apt/lists/* \
    && rm -rf /opt/google/chrome/swiftshader /opt/google/chrome/libswiftshader* \
    && rm -rf /usr/lib/x86_64-linux-gnu/libswiftshader*

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

RUN python -m playwright install chromium 2>/dev/null || true
RUN python -m patchright install chromium 2>/dev/null || true

WORKDIR /app
COPY . .

ENV PORT=5000 HOST=0.0.0.0
ENV DISPLAY=:99
EXPOSE 5000
CMD ["sh", "-c", "Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp &>/dev/null & sleep 1 && python webapp.py"]
