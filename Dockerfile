# Use an official Python runtime as a parent image
FROM python:3.8-alpine

# Set the working directory to /app
WORKDIR /app

# Copy the current directory contents into the container at /app
COPY . /app

# Install any needed packages specified in requirements.txt
RUN apk --update add --virtual build-dependencies python-dev build-base wget gcc libffi-dev openssl-dev \
    && pip install --trusted-host pypi.python.org -r requirements.txt \
    && apk del build-dependencies

# Define environment variable
ENV TOKEN X
ENV CHATID X
ENV DELAY 60

# Run app.py when the container launches
CMD ["python", "telegramRSSbot.py"]