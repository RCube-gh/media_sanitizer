FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
# ffmpeg: for video processing
# imagemagick: for additional image processing (optional but good to have)
# libmagic1: for python-magic file type detection
RUN apt-get update && apt-get install -y \
    ffmpeg \
    imagemagick \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code (will be created in next step)
# For development, we might strictly rely on volume mounts, but copying safe defaults is good practices.
# We will copy sanitizer.py later or rely on mapped volumes if we want to edit live.
# For this PoC, we will assume sanitizer.py is part of the build or mounted. 
# Let's simple copy it. Note: sanitizer.py doesn't exist yet, so this might fail build if not present using COPY.
# To avoid build errors before the file exists, we can touch it or just COPY . .
COPY . .

# Run the sanitizer script
CMD ["python", "-u", "sanitizer.py"]
