FROM alpine/git:latest AS builder

WORKDIR /app

COPY . /app

RUN echo "$(git describe --tags --always)@$(git branch --show-current)" | tee .version

#----------------------------------------

FROM python:3.9-slim

WORKDIR /app

COPY --from=builder /app /app

RUN pip install --trusted-host pypi.python.org -r /app/requirements.txt

CMD ["python", "-u", "telegramRSSbot.py"]
