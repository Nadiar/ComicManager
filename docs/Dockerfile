# Dockerfile for VitePress: build the site, then serve the static files with nginx
FROM node:18-alpine AS build

WORKDIR /app

COPY package*.json ./
RUN npm install

COPY . .
RUN npm run docs:build

FROM nginx:alpine

# The nginx image can lag behind Alpine's security fixes
RUN apk upgrade --no-cache

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/.vitepress/dist /usr/share/nginx/html

EXPOSE 80
