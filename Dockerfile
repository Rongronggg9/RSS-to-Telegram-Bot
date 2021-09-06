# Use an official Python runtime as a parent image
FROM python:3.7-slim

# Set the working directory to /app
WORKDIR /app

# Copy the current directory contents into the container at /app
COPY . /app

# Install any needed packages specified in requirements.txt
RUN pip install --trusted-host pypi.python.org -r /app/requirements.txt
# Define environment variable
ENV PYTHONUNBUFFERED 1
ENV TOKEN X
ENV CHATID X
ENV MANAGER X
ENV DELAY 300
ENV T_PROXY X
ENV R_PROXY X

# Run app.py when the container launches
CMD ["python", "-u", "telegramRSSbot.py"]