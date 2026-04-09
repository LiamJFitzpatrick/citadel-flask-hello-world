FROM python:3.14-alpine

# Create user
RUN adduser -D flaskUser

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apk add --no-cache gcc musl-dev libffi-dev

# Copy requirements first (better caching)
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY ./hello-world/ .

# Create uploads directory
RUN mkdir -p uploads

# Change ownership of the entire app directory to flaskUser
RUN chown -R flaskUser:flaskUser /app

# Switch to non-root user
USER flaskUser

# Expose port
EXPOSE 5000

# Start Flask application
CMD ["gunicorn", "-b", "0.0.0.0:5000", "app:app"]