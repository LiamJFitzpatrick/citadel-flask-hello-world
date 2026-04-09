import os
import pandas as pd
import redis
import json
import boto3
import pika
import logging
from datetime import datetime, timedelta
import tempfile
import signal
import sys
import time
from botocore.exceptions import ClientError

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Valkey connection (using redis client as Valkey is protocol-compatible)
VALKEY_HOST = os.getenv('VALKEY_HOST', os.getenv('REDIS_HOST', 'localhost'))
VALKEY_PORT = int(os.getenv('VALKEY_PORT', os.getenv('REDIS_PORT', 6379)))
valkey_client = redis.Redis(host=VALKEY_HOST, port=VALKEY_PORT, decode_responses=True)

# RustFS/S3 configuration
S3_ENDPOINT = os.getenv('S3_ENDPOINT', 'localhost:9000')
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

def ensure_bucket_exists(retries=5, delay=10):
    """Ensure the MinIO bucket exists, creating it if necessary."""
    logger = logging.getLogger(__name__)

    for attempt in range(1, retries + 1):
        try:
            buckets = s3_client.list_buckets()
            if any(b["Name"] == S3_BUCKET_NAME for b in buckets.get("Buckets", [])):
                logger.info(f"Bucket {S3_BUCKET_NAME} exists")
                return True

            logger.info(f"Bucket {S3_BUCKET_NAME} does not exist. Creating...")
            s3_client.create_bucket(Bucket=S3_BUCKET_NAME)
            logger.info(f"Bucket {S3_BUCKET_NAME} created")
            return True

        except ClientError as e:
            logger.error(f"AWS/MinIO error: {e}")

        except Exception as e:
            logger.error(f"Unexpected error: {e}")

        if attempt < retries:
            logger.info(f"Retrying in {delay}s... ({attempt}/{retries})")
            time.sleep(delay)

    logger.error(f"Could not ensure bucket {S3_BUCKET_NAME} exists after {retries} attempts")
    return False

# Call the function to ensure bucket exists
ensure_bucket_exists()

# RabbitMQ configuration
RABBITMQ_HOST = os.getenv('RABBITMQ_HOST', 'localhost')
RABBITMQ_PORT = int(os.getenv('RABBITMQ_PORT', 5672))
RABBITMQ_USER = os.getenv('RABBITMQ_USER', 'guest')
RABBITMQ_PASS = os.getenv('RABBITMQ_PASS', 'guest')
RABBITMQ_QUEUE = os.getenv('RABBITMQ_QUEUE', 'metrics-processing')

# Global flag for graceful shutdown
running = True

def signal_handler(sig, frame):
    global running
    logger.info("Received shutdown signal, stopping worker...")
    running = False

# Register signal handlers
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

def calculate_metrics(df):
    """Calculate metrics from dataframe"""
    # Convert date columns
    df['signup_date'] = pd.to_datetime(df['signup_date'])
    df['last_active_date'] = pd.to_datetime(df['last_active_date'])
    df['churned'] = df['churned'].astype(bool)
    
    metrics = {}
    
    # 1. Monthly Recurring Revenue (MRR)
    metrics['mrr'] = df.loc[~df['churned'], 'monthly_revenue'].sum()
    
    # 2. Churn Rate
    total_users = len(df)
    churned_users = df['churned'].sum()
    metrics['churn_rate'] = (churned_users / total_users) * 100 if total_users > 0 else 0
    
    # 3. Active Users (last active within last 30 days)
    thirty_days_ago = datetime.now() - timedelta(days=30)
    metrics['active_users'] = len(df[df['last_active_date'] >= thirty_days_ago])
    
    # 4. Average Revenue Per User (ARPU)
    paying_users = df[(~df['churned']) & (df['monthly_revenue'] > 0)]
    metrics['arpu'] = paying_users['monthly_revenue'].mean() if len(paying_users) > 0 else 0
    
    # 5. Revenue by Plan
    revenue_by_plan = df.groupby('plan')['monthly_revenue'].sum().to_dict()
    metrics['revenue_by_plan'] = revenue_by_plan
    
    # 6. Users by Acquisition Channel
    users_by_channel = df['acquisition_channel'].value_counts().to_dict()
    metrics['users_by_acquisition_channel'] = users_by_channel
    
    # 7. Churn by Plan
    churn_by_plan = df[df['churned']].groupby('plan').size().to_dict()
    metrics['churn_by_plan'] = churn_by_plan
    
    # 8. Growth Over Time (Monthly Active Users)
    df['last_active_month'] = df['last_active_date'].dt.to_period('M')
    mau_by_month = df.groupby('last_active_month').size()
    # Convert Period objects to strings for JSON serialization
    mau_dict = {str(k): int(v) for k, v in mau_by_month.items()}
    metrics['growth_over_time'] = mau_dict
    
    return metrics

def store_metrics(metrics):
    """Store metrics in Valkey with NumPy serialization support"""
    try:
        for key, value in metrics.items():
            # The 'default=int' or a lambda works for single NumPy scalars.
            # Using .item() is safer as it converts any NumPy scalar to its Python native type.
            serialized_value = json.dumps(
                value, 
                default=lambda x: x.item() if hasattr(x, 'item') else str(x)
            )
            valkey_client.set(f"metric:{key}", serialized_value)
            
        logger.info("Successfully stored metrics in Valkey")
        return True
    except Exception as e:
        logger.error(f"Failed to store metrics in Valkey: {str(e)}")
        return False

def process_message(ch, method, properties, body):
    """Process a message from RabbitMQ"""
    try:
        message = json.loads(body)
        logger.info(f"Received message: {message}")
        
        # Extract S3 information
        bucket = message.get('bucket')
        key = message.get('key')
        original_filename = message.get('original_filename', 'unknown')
        
        if not bucket or not key:
            logger.error("Invalid message: missing bucket or key")
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
            return
        
        # Download file from RustFS/S3 to temporary location
        with tempfile.NamedTemporaryFile(mode='wb', suffix='.csv', delete=False) as temp_file:
            try:
                s3_client.download_file(bucket, key, temp_file.name)
                temp_file_path = temp_file.name
                
                # Process the CSV
                logger.info(f"Processing file: {original_filename}")
                df = pd.read_csv(temp_file.name)
                metrics = calculate_metrics(df)
                
                # Store metrics in Valkey
                if store_metrics(metrics):
                    logger.info(f"Successfully processed and stored metrics for {original_filename}")
                    ch.basic_ack(delivery_tag=method.delivery_tag)
                else:
                    logger.error(f"Failed to store metrics for {original_filename}")
                    ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
                    
            except Exception as e:
                logger.error(f"Error processing file {original_filename}: {str(e)}")
                ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
            finally:
                # Clean up temporary file
                try:
                    os.unlink(temp_file_path)
                except:
                    pass
                    
    except json.JSONDecodeError:
        logger.error("Invalid JSON in message")
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
    except Exception as e:
        logger.error(f"Unexpected error processing message: {str(e)}")
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)

def main():
    logger.info("Starting metrics worker...")
    
    # Set up RabbitMQ connection
    try:
        connection = pika.BlockingConnection(
            pika.ConnectionParameters(
                host=RABBITMQ_HOST,
                port=RABBITMQ_PORT,
                credentials=pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS),
                heartbeat=600,
                blocked_connection_timeout=300
            )
        )
        channel = connection.channel()
        
        # Ensure queue exists
        channel.queue_declare(queue=RABBITMQ_QUEUE, durable=True)
        
        # Set QoS to process one message at a time
        channel.basic_qos(prefetch_count=1)
        
        # Set up consumer
        channel.basic_consume(
            queue=RABBITMQ_QUEUE,
            on_message_callback=process_message
        )
        
        logger.info(f"Worker started. Waiting for messages on queue: {RABBITMQ_QUEUE}")
        
        # Start consuming
        while running:
            connection.process_data_events(time_limit=1)
            
    except Exception as e:
        logger.error(f"Failed to connect to RabbitMQ: {str(e)}")
        # Wait before retrying
        import time
        time.sleep(5)
        if running:
            main()  # Retry
    finally:
        try:
            if 'connection' in locals() and connection.is_open:
                connection.close()
        except:
            pass
        logger.info("Worker stopped.")

if __name__ == "__main__":
    main()