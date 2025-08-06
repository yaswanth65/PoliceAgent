FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Expose the port your app runs on
EXPOSE 5000

# Use gunicorn for production
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:5000"]