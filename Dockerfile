FROM python:3.10-bullseye AS venv-initializer

# initialize venv
RUN \
    set -ex && \
    python -m venv --copies /opt/venv && \
    export PATH=/opt/venv/bin:$PATH && \
    pip install --no-cache-dir --upgrade \
        pip setuptools wheel

#-----------------------------------------------------------------------------------------------------------------------

FROM debian:bullseye AS dep-parser

WORKDIR /ver

COPY requirements.txt .

RUN \
    set -ex && \
    grep 'cryptg' requirements.txt | tee cryptg.ver && \
    sed '/cryptg/d' requirements.txt > requirements-no-cryptg.txt

#-----------------------------------------------------------------------------------------------------------------------

FROM python:3.10-bullseye AS cryptg-builder
# cryptg has no dependencies, so we can just build it in a separate stage and concatenate the results with dep-builder

# https://hub.docker.com/_/rust
COPY --from=rust:1-slim-bullseye /usr/local/cargo /usr/local/cargo
COPY --from=rust:1-slim-bullseye /usr/local/rustup /usr/local/rustup

COPY --from=venv-initializer /opt/venv /opt/venv

# activate venv and rustup
ENV PATH="/opt/venv/bin:/usr/local/cargo/bin:$PATH" \
    CARGO_HOME=/usr/local/cargo \
    RUSTUP_HOME=/usr/local/rustup

COPY --from=dep-parser /ver/cryptg.ver /ver/cryptg.ver

RUN \
    set -ex && \
    rustup --version && \
    cargo --version && \
    rustc --version && \
    pip install --no-cache-dir \
        $(cat /ver/cryptg.ver) \
    && \
    rm -rf /opt/venv/src

#-----------------------------------------------------------------------------------------------------------------------

FROM python:3.10-bullseye AS dep-builder

COPY --from=venv-initializer /opt/venv /opt/venv

# activate venv
ENV PATH="/opt/venv/bin:$PATH"

COPY --from=dep-parser /ver/requirements-no-cryptg.txt /ver/requirements-no-cryptg.txt

RUN \
    set -ex && \
    pip install --no-cache-dir \
        -r /ver/requirements-no-cryptg.txt \
    && \
    rm -rf /opt/venv/src

#-----------------------------------------------------------------------------------------------------------------------

FROM python:3.10-bullseye as app-builder

WORKDIR /app

COPY . /app

# inject railway env vars
ARG RAILWAY_GIT_COMMIT_SHA
ARG RAILWAY_GIT_BRANCH

RUN \
    set -ex && \
    echo "$(expr substr "$RAILWAY_GIT_COMMIT_SHA" 1 7)@$RAILWAY_GIT_BRANCH" | tee .version && \
    if test $(expr length "$(cat .version)") -le 3; then \
        echo "$(git describe --tags --always)@$(git branch --show-current)" | tee .version ; \
    fi && \
    if test $(expr length "$(cat .version)") -le 3; then \
        echo "dirty-build@$(date -Iseconds)" | tee .version; else echo "build@$(date -Iseconds)" | tee -a .version; \
    fi && \
    mkdir /app-minimal && \
    cp -r .version LICENSE src telegramRSSbot.py /app-minimal && \
    cd / && \
    rm -rf /app && \
    rm -f /app-minimal/*.md && \
    ls -la /app-minimal && \
    du -hd1 /app-minimal && \
    cat /app-minimal/.version

#-----------------------------------------------------------------------------------------------------------------------

FROM python:3.10-slim-bullseye as app

# install fonts
RUN \
    set -ex && \
    apt-get update && \
    apt-get install -yq --no-install-recommends \
        fonts-wqy-microhei \
    && \
    rm -rf /var/lib/apt/lists/*

# install wkhtmltopdf  # hmmm, wkhtmltopdf works strangely...
#RUN \
#    apt-get update && apt-get -y install wget && \
#    wget "https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6-1/wkhtmltox_0.12.6-1.buster_$(dpkg --print-architecture).deb" -O /tmp/wkhtmltopdf.deb && \
#    dpkg -i /tmp/wkhtmltopdf.deb && apt-get -f install && \
#    rm -f /tmp/wkhtmltopdf.deb && apt-get purge wget --auto-remove

WORKDIR /app

# activate venv
ENV PATH="/opt/venv/bin:$PATH"

ENV PYTHONUNBUFFERED=1

COPY --from=cryptg-builder /opt/venv /opt/venv
COPY --from=dep-builder /opt/venv /opt/venv
COPY --from=app-builder /app-minimal /app

# verify cryptg installation
RUN python -c 'import logging; logging.basicConfig(level=logging.DEBUG); import telethon; import cryptg'

CMD ["python", "-u", "telegramRSSbot.py"]
