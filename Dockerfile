FROM python:3.10-slim-bullseye AS dep-builder

RUN \
    set -ex && \
    apt-get update && \
    apt-get install -yq --no-install-recommends \
        gcc g++ libc6-dev \
    && \
    rm -rf /var/lib/apt/lists/*

# initialize venv
RUN \
    set -ex && \
    python -m venv --copies /opt/venv && \
    export PATH=/opt/venv/bin:$PATH && \
    pip install --use-feature=fast-deps --no-cache-dir --upgrade \
        pip setuptools wheel

# https://hub.docker.com/_/rust
COPY --from=rust:1-slim-bullseye /usr/local/cargo /usr/local/cargo
COPY --from=rust:1-slim-bullseye /usr/local/rustup /usr/local/rustup

# activate venv and rustup
ENV PATH="/opt/venv/bin:/usr/local/cargo/bin:$PATH" \
    CARGO_HOME=/usr/local/cargo \
    RUSTUP_HOME=/usr/local/rustup

COPY requirements.txt .

RUN \
    set -ex && \
    rustup --version && \
    cargo --version && \
    rustc --version && \
    pip install --use-feature=fast-deps --no-cache-dir \
        -r requirements.txt \
    && \
    rm -rf /opt/venv/src

#-----------------------------------------------------------------------------------------------------------------------

FROM python:3.10-slim-bullseye as app-builder

WORKDIR /app

RUN \
    set -ex && \
    apt-get update && \
    apt-get install -yq --no-install-recommends \
        git \
    && \
    rm -rf /var/lib/apt/lists/*

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

COPY --from=dep-builder /opt/venv /opt/venv
COPY --from=app-builder /app-minimal /app

CMD ["python", "-u", "telegramRSSbot.py"]
