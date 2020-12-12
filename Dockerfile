FROM python:3.9-alpine

RUN addgroup -g 1000 -S appgroup && adduser -S appuser -u 1000 -D -h /home/appuser -G appgroup -s /bin/sh

RUN apk add gcc libc-dev linux-headers

WORKDIR /home/appuser/app
ENV FLASK_APP=app.py
ENV FLASK_RUN_HOST=0.0.0.0
COPY requirements.txt requirements.txt
RUN pip install -r requirements.txt
EXPOSE 8080
COPY . .

RUN chown -R appuser /home/appuser

CMD ["uwsgi", "app.ini"]
