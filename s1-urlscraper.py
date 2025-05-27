import mysql.connector
import pandas as pd
import os
import time
import logging
import glob
from datetime import datetime
from dotenv import load_dotenv

# Force load from the specific path
env_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(env_path)


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("logs/s1-urlscraper.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger()

def connect_to_database():
    """Connect to MySQL database using environment variables."""
    try:
        # Force log the values to see what's happening
        host = os.environ.get('DB_HOST')
        user = os.environ.get('DB_USER') 
        password = os.environ.get('DB_PASSWORD')
        database = os.environ.get('DB_NAME')
        
        # Log values
        logger.info(f"Environment variables:")
        logger.info(f"DB_HOST = {host}")
        logger.info(f"DB_USER = {user}")
        logger.info(f"DB_NAME = {database}")
        
        # DEBUG: Print the raw DB_PORT value
        raw_port = os.getenv('DB_PORT', '3306')
        logger.info(f"Raw DB_PORT value: {raw_port}")
        
        # Handle bad port value
        try:
            port = int(raw_port)
        except ValueError:
            logger.warning(f"Invalid DB_PORT value: '{raw_port}', using default 13306")
            port = 13306
        
        logger.info(f"Attempting to connect to MySQL at {host}:{port}...")
        
        connection = mysql.connector.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database
        )
        
        logger.info(f"Successfully connected to MySQL database at {host}:{port}")
        return connection
    except mysql.connector.Error as err:
        logger.error(f"Error connecting to MySQL: {err}")
        return None

def get_all_processed_urls():
    """Get all URLs that have been processed (from both mp4hls-videos.csv and all batch files)."""
    processed_urls = set()
    
    # Check main CSV file
    main_csv = os.getenv('MAIN_CSV_PATH', "/pymp4hls/mp4hls-videos.csv")
    if os.path.exists(main_csv):
        try:
            df = pd.read_csv(main_csv)
            if 'content_url' in df.columns:
                processed_urls.update(df['content_url'].tolist())
        except Exception as e:
            logger.error(f"Error reading main CSV: {e}")
    
    # Check all batch CSV files
    urls_dir = os.getenv('URLS_DIR', "/pymp4hls/urls")
    batch_files = glob.glob(os.path.join(urls_dir, "urlscrapped_batch-*.csv"))
    for batch_file in batch_files:
        try:
            df = pd.read_csv(batch_file)
            if 'content_url' in df.columns:
                processed_urls.update(df['content_url'].tolist())
        except Exception as e:
            logger.error(f"Error reading batch file {batch_file}: {e}")
    
    logger.info(f"Found {len(processed_urls)} already processed URLs")
    return processed_urls

def get_next_batch_number():
    """Find the next available batch number."""
    urls_dir = os.getenv('URLS_DIR', "/pymp4hls/urls")
    batch_files = glob.glob(os.path.join(urls_dir, "urlscrapped_batch-*.csv"))
    if not batch_files:
        return 1
        
    batch_numbers = []
    for file in batch_files:
        try:
            # Extract the batch number from filenames like "urlscrapped_batch-1.csv"
            batch_num = int(file.split('-')[-1].split('.')[0])
            batch_numbers.append(batch_num)
        except (ValueError, IndexError):
            continue
            
    return max(batch_numbers) + 1 if batch_numbers else 1

def fetch_video_urls(connection, query, processed_urls):
    """Fetch video URLs from database using the provided query,
    excluding already processed URLs."""
    try:
        # Log the SQL query for debugging
        logger.info(f"Executing SQL query: {query}")
        
        cursor = connection.cursor(dictionary=True)
        cursor.execute(query)
        results = cursor.fetchall()
        cursor.close()
        
        if not results:
            logger.info("No new videos found in database")
            return []
            
        # Log results structure for debugging
        if results:
            logger.info(f"First result structure: {list(results[0].keys())}")
            
        logger.info(f"Found {len(results)} video(s) in database")
        
        # Extract URLs from results - use the correct column name
        all_urls = [row['full_url'] for row in results if 'full_url' in row]
        
        # Filter out already processed URLs
        new_urls = [url for url in all_urls if url not in processed_urls]
        
        logger.info(f"{len(all_urls) - len(new_urls)} URLs were already processed")
        logger.info(f"{len(new_urls)} new URLs ready to process")
        
        return new_urls
        
    except mysql.connector.Error as err:
        logger.error(f"Error fetching video URLs: {err}")
        return []

def update_csv_files(main_csv, new_urls):
    """Update both the main CSV file and create a new batch CSV."""
    try:
        # Update main CSV
        if not os.path.exists(main_csv):
            with open(main_csv, 'w') as f:
                f.write("content_url\n")
                
        # Append new URLs
        with open(main_csv, 'a') as f:
            for url in new_urls:
                f.write(f"{url}\n")
                
        logger.info(f"Added {len(new_urls)} new URL(s) to {main_csv}")
        
        # Ensure urls directory exists
        urls_dir = os.getenv('URLS_DIR', "/pymp4hls/urls")
        if not os.path.exists(urls_dir):
            os.makedirs(urls_dir)
            logger.info(f"Created directory {urls_dir}")
        
        # Create batch CSV
        batch_num = get_next_batch_number()
        batch_csv = os.path.join(urls_dir, f"urlscrapped_batch-{batch_num}.csv")
        
        # Write batch with header
        with open(batch_csv, 'w') as f:
            f.write("content_url\n")
            for url in new_urls:
                f.write(f"{url}\n")
                
        logger.info(f"Created batch file {batch_csv} with {len(new_urls)} URLs")
        
        return batch_num
        
    except Exception as e:
        logger.error(f"Error updating CSV files: {e}")
        return None

def main():
    # Get all previously processed URLs from main CSV and all batch files
    processed_urls = get_all_processed_urls()
    
    # Connect to database - modified call without passing config dict
    connection = connect_to_database()
    if not connection:
        return
    
    # Get query from environment
    select_query = os.getenv('DB_SELECT_QUERY')
    
    main_csv = os.getenv('MAIN_CSV_PATH', "/pymp4hls/mp4hls-videos.csv")
    
    try:
        # Fetch new URLs from database (filtering out already processed ones)
        new_urls = fetch_video_urls(connection, select_query, processed_urls)
        
        if new_urls:
            # Update both CSV files
            batch_num = update_csv_files(main_csv, new_urls)
            
            if batch_num:
                # Removed database update - only logging
                logger.info(f"Batch #{batch_num} completed with {len(new_urls)} URLs")
            
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
    finally:
        connection.close()
        logger.info("Database connection closed")

if __name__ == "__main__":
    while True:
        start_time = datetime.now()
        logger.info(f"Starting URL scraper at {start_time}")
        
        main()
        
        end_time = datetime.now()
        duration = end_time - start_time
        logger.info(f"Completed URL scraper in {duration}")
        
        # Wait before next check
        check_interval = int(os.getenv('CHECK_INTERVAL', '300'))
        logger.info(f"Waiting {check_interval} seconds before next database check...")
        time.sleep(check_interval)