FROM python:3.11-slim-bookworm@sha256:2e32f7d302adc1c37428355c1e646897c0c53f4fd60b6a551245fb90ee129f91 AS builder

RUN apt-get update \
  && apt-get install --no-install-recommends -y \
     build-essential libcairo2-dev libffi-dev libgif-dev libjpeg-dev \
     libssl-dev libxml2-dev libxslt1-dev libzbar-dev zlib1g-dev \
  && rm -rf /var/lib/apt/lists/*

ENV VIRTUAL_ENV=/opt/venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"
RUN python -m venv "$VIRTUAL_ENV"

COPY requirements/prod_linux.txt requirements/prod_linux.lock.txt ./requirements/
RUN python -m pip install --no-cache-dir --upgrade pip setuptools wheel \
  && python -m pip install --no-cache-dir -r requirements/prod_linux.lock.txt \
  && sed -i 's/^import pkg_resources$/from importlib.metadata import version as package_version/' \
       /opt/venv/lib/python3.11/site-packages/zbarlight/__init__.py \
  && sed -i "s/^__version__ = pkg_resources.get_distribution('zbarlight').version$/__version__ = package_version('zbarlight')/" \
       /opt/venv/lib/python3.11/site-packages/zbarlight/__init__.py \
  && python -m pip check

FROM builder AS test

WORKDIR /home/appuser/app
COPY . .
RUN python -m pip install --no-cache-dir -r requirements/test.txt

FROM builder AS runtime-venv

RUN python -m pip uninstall -y setuptools wheel \
  && python -m pip uninstall -y pip \
  && rm -f /opt/venv/bin/flaskswagger \
       /opt/venv/lib/python3.11/site-packages/build_swagger_spec.py

FROM python:3.11-slim-bookworm@sha256:2e32f7d302adc1c37428355c1e646897c0c53f4fd60b6a551245fb90ee129f91

RUN groupadd --gid 1001 appuser \
  && useradd --uid 1001 --gid appuser --create-home appuser \
  && apt-get update \
  && apt-get install --no-install-recommends -y \
     libcairo2 libffi8 libgif7 libjpeg62-turbo libxml2 libxslt1.1 libzbar0 zlib1g \
  && apt-get remove -y --allow-remove-essential perl-base \
  && rm -rf /var/lib/apt/lists/* \
  && rm -rf /usr/local/lib/python3.11/site-packages/*

ENV VIRTUAL_ENV=/opt/venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"
COPY --from=runtime-venv /opt/venv /opt/venv

WORKDIR /home/appuser/app

ENV FLASK_APP=app.py
ENV FLASK_RUN_HOST=0.0.0.0

COPY --chown=appuser:root . .
COPY --chown=root:root docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

RUN mkdir -p data logs taxonomy_data \
  && chown -R appuser:appuser /home/appuser \
  && chmod 0755 /usr/local/bin/docker-entrypoint.sh

EXPOSE 8080

USER appuser
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["uwsgi", "app.ini"]
