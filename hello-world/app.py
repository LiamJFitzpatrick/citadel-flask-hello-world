from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
import redis
import json
import os
import boto3
import pika
import uuid
from werkzeug.utils import secure_filename
from datetime import datetime
import threading

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')

# Valkey connection (using redis client as Valkey is protocol-compatible)
VALKEY_HOST = os.getenv('VALKEY_HOST', os.getenv('REDIS_HOST', 'localhost'))
VALKEY_PORT = int(os.getenv('VALKEY_PORT', os.getenv('REDIS_PORT', 6379)))
valkey_client = redis.Redis(host=VALKEY_HOST, port=VALKEY_PORT, decode_responses=True)

# RustFS/S3 configuration
S3_ENDPOINT = os.getenv('S3_ENDPOINT', 'rustfs:9000')
S3_ACCESS_KEY = os.getenv('S3_ACCESS_KEY', 'minioadmin')
S3_SECRET_KEY = os.getenv('S3_SECRET_KEY', 'minioadmin')
S3_BUCKET_NAME = os.getenv('S3_BUCKET_NAME', 'saas-metrics-uploads')
S3_USE_SSL = os.getenv('S3_USE_SSL', 'false').lower() == 'true'

# Initialize S3 client
s3_client = boto3.client(
    's3',
    endpoint_url=f"{'https' if S3_USE_SSL else 'http'}://{S3_ENDPOINT}",
    aws_access_key_id=S3_ACCESS_KEY,
    aws_secret_access_key=S3_SECRET_KEY,
)

# RabbitMQ configuration
RABBITMQ_HOST = os.getenv('RABBITMQ_HOST', 'rabbitmq')
RABBITMQ_PORT = int(os.getenv('RABBITMQ_PORT', 5672))
RABBITMQ_USER = os.getenv('RABBITMQ_USER', 'guest')
RABBITMQ_PASS = os.getenv('RABBITMQ_PASS', 'guest')
RABBITMQ_QUEUE = os.getenv('RABBITMQ_QUEUE', 'metrics-processing')

def get_metrics():
    """Retrieve all metrics from Valkey"""
    metrics = {}
    metric_keys = ['mrr', 'churn_rate', 'active_users', 'arpu', 
                   'revenue_by_plan', 'users_by_acquisition_channel', 
                   'churn_by_plan', 'growth_over_time']
     
    for key in metric_keys:
        value = valkey_client.get(f"metric:{key}")
        if value:
            try:
                metrics[key] = json.loads(value)
            except json.JSONDecodeError:
                metrics[key] = value
        else:
            # Provide default values if metrics not yet available
            if key in ['mrr', 'churn_rate', 'active_users', 'arpu']:
                metrics[key] = 0
            elif key in ['revenue_by_plan', 'users_by_acquisition_channel', 'churn_by_plan']:
                metrics[key] = {}
            elif key == 'growth_over_time':
                metrics[key] = {}
    
    return metrics

def publish_to_queue(message):
    """Publish a message to RabbitMQ queue"""
    try:
        connection = pika.BlockingConnection(
            pika.ConnectionParameters(
                host=RABBITMQ_HOST,
                port=RABBITMQ_PORT,
                credentials=pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)
            )
        )
        channel = connection.channel()
        
        # Ensure queue exists
        channel.queue_declare(queue=RABBITMQ_QUEUE, durable=True)
        
        # Publish message
        channel.basic_publish(
            exchange='',
            routing_key=RABBITMQ_QUEUE,
            body=json.dumps(message),
            properties=pika.BasicProperties(
                delivery_mode=2,  # Make message persistent
            )
        )
        connection.close()
        return True
    except Exception as e:
        app.logger.error(f"Failed to publish to RabbitMQ: {str(e)}")
        return False

@app.route("/")
def dashboard():
    metrics = get_metrics()
    return render_template('dashboard.html', metrics=metrics)

@app.route("/upload", methods=['GET', 'POST'])
def upload_file():
    if request.method == 'POST':
        # Check if file was uploaded
        if 'file' not in request.files:
            flash('No file part')
            return redirect(request.url)
        
        file = request.files['file']
        
        # If user does not select file, browser also
        # submit an empty part without filename
        if file.filename == '':
            flash('No selected file')
            return redirect(request.url)
        
        if file and file.filename.endswith('.csv'):
            try:
                # Secure the filename and create unique key
                original_filename = secure_filename(file.filename)
                unique_id = str(uuid.uuid4())
                object_key = f"{unique_id}_{original_filename}"
                
                # Upload file to RustFS/S3
                s3_client.upload_fileobj(
                    file,
                    S3_BUCKET_NAME,
                    object_key
                )
                
                # Send message to RabbitMQ for processing
                message = {
                    'bucket': S3_BUCKET_NAME,
                    'key': object_key,
                    'original_filename': original_filename,
                    'upload_timestamp': datetime.now().isoformat()
                }
                
                if publish_to_queue(message):
                    flash(f'File {original_filename} uploaded successfully and sent for processing.')
                else:
                    flash(f'File {original_filename} uploaded but failed to queue for processing. Please try again.')
                
                return redirect(url_for('upload_file'))
            except Exception as e:
                app.logger.error(f"Upload error: {str(e)}")
                flash(f'Error uploading file: {str(e)}')
                return redirect(request.url)
        else:
            flash('Please upload a CSV file')
            return redirect(request.url)
    
    return render_template('upload.html')

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)