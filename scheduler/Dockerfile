FROM alpine:3.21
RUN apk add --no-cache docker-cli docker-cli-compose jq tzdata
COPY crontab /etc/crontabs/root
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
