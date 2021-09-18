FROM alpine/git:latest AS builder

WORKDIR /app

COPY . /app

RUN \
  echo -n "$(git describe --tags --always)@$(git branch --show-current)" > .version ; \
  if test $(expr length "$(cat .version)") -le 3; then echo "dirty-build-$(date -Iseconds)" | tee .version; else echo "@build-$(date -Iseconds)" | tee -a .version; fi ; \
  rm -rf .git resources

#----------------------------------------

FROM python:3.9-slim

WORKDIR /app

COPY --from=builder /app /app

RUN \
  pip install --trusted-host pypi.python.org -r /app/requirements.txt && \
  ls -la ; \
  cat .version

CMD ["python", "-u", "telegramRSSbot.py"]
