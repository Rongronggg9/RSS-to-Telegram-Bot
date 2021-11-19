FROM python:3.9-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y build-essential git

# initialize venv
RUN python -m venv /app/venv

# activate venv
ENV PATH="/app/venv/bin:$PATH"

# upgrade venv deps
RUN pip install --trusted-host pypi.python.org --upgrade pip setuptools wheel

COPY requirements.txt /app

RUN pip install --trusted-host pypi.python.org -r /app/requirements.txt

COPY . /app

RUN \
    echo "$(git describe --tags --always)@$(git branch --show-current)" | tee .version ; \
    if test $(expr length "$(cat .version)") -le 3; then echo "dirty-build@$(date -Iseconds)" | tee .version; else echo "build@$(date -Iseconds)" | tee -a .version; fi ; \
    rm -rf .git .github resources config && \
    mkdir -p config && \
    ls -la ; \
    cat .version

#----------------------------------------

FROM python:3.9-slim

WORKDIR /app

COPY --from=builder /app /app

# activate venv
ENV PATH="/app/venv/bin:$PATH"

ENV PYTHONUNBUFFERED=1

CMD ["python", "-u", "telegramRSSbot.py"]
