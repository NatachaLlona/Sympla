FROM nginxinc/nginx-unprivileged:stable-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY public /usr/share/nginx/html
ENTRYPOINT []
CMD ["nginx", "-g", "daemon off;"]
