FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    nodejs \
    npm \
    p7zip-full \
    unrar-free \
    libmagic1 \
    file \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npx tailwindcss -i ./static/css/input.css -o ./static/css/main.css --minify

RUN apt-get purge -y nodejs npm && apt-get autoremove -y \
    && rm -rf /root/.npm node_modules

RUN mkdir -p /app/staticfiles /app/logs && chmod 777 /app/staticfiles /app/logs

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["/entrypoint.sh"]
