FROM python:3.11-slim

# Set environment variables to optimize Python and configure Streamlit
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    STREAMLIT_SERVER_PORT=8080 \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_SERVER_ENABLE_CORS=false \
    STREAMLIT_SERVER_HEADLESS=true

# Create a non-root user and group
RUN useradd -m -r appuser

# Set the working directory
WORKDIR /app

# Copy requirements first to leverage Docker layer caching
COPY requirements.txt .

# Install Python dependencies globally within the container
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt
# Copy the remaining project files
COPY . .

# Adjust permissions so the non-root user owns the app directory
RUN chown -R appuser:appuser /app

# Switch to the non-root user for security
USER appuser

# Expose the port Streamlit runs on
EXPOSE 8080

# Run the Streamlit application
CMD ["streamlit", "run", "app.py"]
