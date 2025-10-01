# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set the working directory in the container to /app
WORKDIR /app

# Copy the requirements file into the container at /app
COPY ./requirements.txt .

# Install any needed packages specified in requirements.txt
# --no-cache-dir makes the image smaller
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the backend application code into the container at /app
# The volume mount in docker-compose will overwrite this, but it's good practice for production builds
COPY . .

# The command to run the application will be specified in docker-compose.yml
# This allows for flexibility (e.g., using --reload for development)
