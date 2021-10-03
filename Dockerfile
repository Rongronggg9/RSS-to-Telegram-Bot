FROM alpine/git:latest AS builder

WORKDIR /app

COPY . /app

RUN \
  echo "$(git describe --tags --always)@$(git branch --show-current)" > .version ; \
  if test $(expr length "$(cat .version)") -le 3; then echo "dirty-build@$(date -Iseconds)" | tee .version; else echo "build@$(date -Iseconds)" | tee -a .version; fi ; \
  rm -rf .git .github resources && \
  mkdir -p config

#----------------------------------------

FROM python:3.9-slim

WORKDIR /app

COPY --from=builder /app /app

RUN apt-get update && apt-get install -y gcc && \
  pip install --trusted-host pypi.python.org -r /app/requirements.txt && \
  apt-get purge -y gcc && apt-get autoremove --purge -y && \
  ls -la ; \
  cat .version

CMD ["python", "-u", "telegramRSSbot.py"]
