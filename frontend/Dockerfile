# Stage 1: build React app using the official multi-arch Node image (ARM64 native on Mac)
FROM node:20-alpine AS builder

WORKDIR /app
COPY package.json ./
RUN npm install

COPY . .
RUN npm run build

# Stage 2: serve with nginx (amd64-safe, no JS execution)
FROM registry.access.redhat.com/ubi9/nginx-120:latest

COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/nginx.conf

EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
