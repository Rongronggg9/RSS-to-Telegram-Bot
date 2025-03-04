#  RSS to Telegram Bot
#  Copyright (C) 2024  Rongrong <i@rong.moe>
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU Affero General Public License as
#  published by the Free Software Foundation, either version 3 of the
#  License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU Affero General Public License for more details.
#
#  You should have received a copy of the GNU Affero General Public License
#  along with this program.  If not, see <https://www.gnu.org/licenses/>.

FROM python:3.12-bookworm AS dep-builder-common

ENV PATH="/opt/venv/bin:$PATH"

RUN \
    set -ex && \
    python -m venv --copies /opt/venv && \
    python -m pip install --no-cache-dir --upgrade \
        pip setuptools wheel

COPY requirements.txt .

RUN \
    set -ex && \
    export MAKEFLAGS="-j$((`nproc`+1))" && \
    pip install --no-cache-dir \
        -r requirements.txt \
    && \
    rm -rf /opt/venv/src

#-----------------------------------------------------------------------------------------------------------------------

FROM python:3.12-bookworm AS dep-builder

ENV PATH="/opt/venv/bin:$PATH"
ARG EXP_REGEX='^([^~=<>]+)[^#]*#\s*(\1@.+)$'

COPY requirements.txt .
RUN \
    set -ex && \
    pip wheel --no-cache-dir --no-deps \
        $(sed -nE "s/$EXP_REGEX/\2/p" requirements.txt)

COPY --from=dep-builder-common /opt/venv /opt/venv

ARG EXP_DEPS=0
RUN \
    set -ex && \
    if [ "$EXP_DEPS" = 1 ]; then \
        AFFECTED_PKGS=$(sed -nE "s/$EXP_REGEX/\1/p" requirements.txt); \
        pip uninstall -y $AFFECTED_PKGS && \
        for pkg in $AFFECTED_PKGS; do \
            sed -Ei "s#$pkg.*#$(find . -iname "${pkg}-*.whl")#" requirements.txt; \
        done; \
        pip install --no-cache-dir \
            -r requirements.txt \
        ; \
    fi;

#-----------------------------------------------------------------------------------------------------------------------

FROM buildpack-deps:bookworm AS mimalloc-builder

WORKDIR /mimalloc

RUN \
    set -ex && \
    apt-get update && \
    apt-get install -yq --no-install-recommends \
        cmake \
    && \
    curl -sL https://github.com/microsoft/mimalloc/archive/refs/tags/v2.0.9.tar.gz | tar -zxf - --strip-components=1 && \
    mkdir -p build/lib && \
    cd build && \
    cmake .. && \
    make mimalloc -j$((`nproc`+1)) && \
    ln libmimalloc.so* lib/ && \
    apt-get purge -yq --auto-remove \
        cmake \
    && \
    rm -rf /var/lib/apt/lists/*

#-----------------------------------------------------------------------------------------------------------------------

FROM python:3.12-bookworm AS app-builder

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

FROM python:3.12-slim-bookworm AS app

WORKDIR /app

RUN \
    set -ex && \
    apt-get update && \
    apt-get install -yq --no-install-recommends \
        fonts-wqy-microhei libjemalloc2 \
    && \
    rm -rf /var/lib/apt/lists/*

ENV \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    RAPIDFUZZ_IMPLEMENTATION=cpp \
    PYTHONMALLOC=malloc \
    LD_PRELOAD=libjemalloc.so.2 \
    MALLOC_CONF=background_thread:true,max_background_threads:1,metadata_thp:auto,dirty_decay_ms:80000,muzzy_decay_ms:80000
    # jemalloc tuning, Ref:
    # https://github.com/home-assistant/core/pull/70899
    # https://github.com/jemalloc/jemalloc/blob/5.2.1/TUNING.md

COPY --from=mimalloc-builder /mimalloc/build/lib /usr/local/lib
COPY --from=dep-builder /opt/venv /opt/venv
COPY --from=app-builder /app-minimal /app

# verify cryptg installation
RUN python -c 'import logging; logging.basicConfig(level=logging.DEBUG); import telethon; import cryptg'

ENTRYPOINT ["python", "-u", "telegramRSSbot.py"]
