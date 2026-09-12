FROM node:20-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

ARG VITE_API_BASE_URL=/ai-commons/api
ARG VITE_PUBLIC_BASE=/ai-commons/
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL} \
    VITE_PUBLIC_BASE=${VITE_PUBLIC_BASE}

RUN npm run build

FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 5173
