FROM alpine:3
RUN apk add --no-cache rsyslog rsyslog-relp logger
ADD rsyslog.conf /etc
EXPOSE 514 10514
CMD ["rsyslogd", "-n"]
