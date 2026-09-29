# Stage 1: build the static site with Node.
FROM node:24-alpine AS build
WORKDIR /app
# Install dependencies first so this layer stays cached until package files change.
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

# Stage 2: serve the built files with nginx. Node isn't in the final image at all.
FROM nginx:stable-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
