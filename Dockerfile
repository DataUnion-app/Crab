FROM ubuntu:20.04

RUN useradd -rm -d /home/appuser -s /bin/bash -g root -G sudo -u 1001 appuser

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
  && apt-get install -y python3-pip python3-dev \
  && cd /usr/local/bin \
  && ln -s /usr/bin/python3 python \
  && pip3 --no-cache-dir install --upgrade pip \
  && rm -rf /var/lib/apt/lists/*

RUN apt-get update && apt-get install vim -y && apt-get install less -y

WORKDIR /home/appuser/app
ENV FLASK_APP=app.py
ENV FLASK_RUN_HOST=0.0.0.0
COPY requirements/prod_linux.txt requirements.txt
RUN pip install -r requirements.txt
EXPOSE 8080
COPY . .

RUN chown -R appuser /home/appuser

CMD ["uwsgi", "app.ini"]
