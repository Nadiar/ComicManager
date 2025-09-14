FROM python:3.12-slim

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    nodejs \
    npm \
    p7zip-full \
    unrar-free \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Node deps and build CSS
COPY package.json .
RUN npm install

COPY . .
RUN npx tailwindcss -i ./static/css/input.css -o ./static/css/main.css --minify

# Remove Node after CSS build — not needed at runtime
RUN apt-get purge -y nodejs npm && apt-get autoremove -y && rm -rf /root/.npm

RUN python manage.py collectstatic --noinput

EXPOSE 8000
