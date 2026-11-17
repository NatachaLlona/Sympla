FROM nginxinc/nginx-unprivileged:stable-alpine
COPY audience-map/nginx.conf /etc/nginx/conf.d/default.conf
COPY audience-map/public /usr/share/nginx/html/map
# Shared visual primitives are copied at build time; there is no runtime asset dependency.
COPY frontend/public/styles.css frontend/public/favicon.svg /usr/share/nginx/html/map/
ENTRYPOINT []
CMD ["nginx", "-g", "daemon off;"]
