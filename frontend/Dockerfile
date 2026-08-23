FROM node:26-trixie-slim AS build
WORKDIR /app
COPY package-lock.json package.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.31.3-alpine-slim
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf