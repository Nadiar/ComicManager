FROM python:3.12-slim-trixie

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
# pip is only needed for the build; removing it also removes the old packages it bundles
RUN pip install --no-cache-dir -r requirements.txt && pip uninstall -y -q pip

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npx tailwindcss -i ./static/css/input.css -o ./static/css/main.css --minify

RUN apt-get purge -y nodejs npm && apt-get autoremove -y \
    && rm -rf /root/.npm node_modules

RUN mkdir -p /app/staticfiles /app/logs && chmod -R 777 /app/staticfiles /app/logs

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["/entrypoint.sh"]
