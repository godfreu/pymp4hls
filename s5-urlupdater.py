import os
import time
import logging
import mysql.connector
import glob
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
env_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(env_path)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("logs/s5-urlupdater.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger()

def connect_to_database(max_retries=3, retry_delay=5):
    """Connect to MySQL database with retry logic for SSH tunnel failures."""
    retries = 0
    while retries < max_retries:
        try:
            host = os.getenv('DB_HOST')
            port = int(os.getenv('DB_PORT', '13306'))
            user = os.getenv('DB_USER') 
            password = os.getenv('DB_PASSWORD')
            database = os.getenv('DB_NAME')
            
            logger.info(f"Attempting to connect to MySQL at {host}:{port} (attempt {retries+1}/{max_retries})...")
            
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
            retries += 1
            if retries < max_retries:
                logger.info(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
    
    return None

def find_uploaded_videos():
    """
    Find videos that have been successfully uploaded to S3 by reading the CSV batch files.
    Returns a list of dictionaries with hls_name, upload_time, etc.
    """
    uploads_dir = os.getenv('UPLOADS_DIR', 'uploads')
    processed_marker = os.getenv('PROCESSED_MARKER_DIR', os.path.join(uploads_dir, 'processed'))
    os.makedirs(processed_marker, exist_ok=True)
    
    hls_videos = []
    
    # Look for CSV batch files in the uploads directory
    batch_files = glob.glob(os.path.join(uploads_dir, "uploaded-*.csv"))
    
    for batch_file in batch_files:
        try:
            # Check if we've already processed this batch
            batch_name = os.path.basename(batch_file)
            marker_file = os.path.join(processed_marker, f"{batch_name}.processed")
            
            if os.path.exists(marker_file):
                logger.info(f"Skipping already processed batch: {batch_name}")
                continue
                
            # Read the CSV file
            df = pd.read_csv(batch_file)
            logger.info(f"Reading batch file {batch_file} with {len(df)} entries")
            
            # Process each row in the CSV
            for _, row in df.iterrows():
                hls_name = row.get('hls_name')
                upload_time = row.get('upload_time')
                
                if hls_name:
                    # Build the metadata needed for database updates
                    s3_bucket = os.getenv('S3_BUCKET_NAME', 'gk-hls')
                    s3_region = os.getenv('S3_REGION', 'ap-southeast-1')
                    s3_prefix = os.getenv('S3_PREFIX', 'opt/courses/')
                    
                    # Construct the S3 URL for the HLS playlist
                    hls_path = f"{s3_prefix}{hls_name}/{hls_name}.m3u8"  # Just the path part
                    
                    # Try to determine original_url from hls_name
                    # This assumes hls_name is based on the original MP4 filename
                    original_url = f"https://staging-static.gokampus.com/{hls_name}.mp4"
                    
                    hls_videos.append({
                        'hls_name': hls_name,
                        'original_url': original_url,
                        'hls_url': hls_path,
                        'upload_time': upload_time,
                        'batch_file': batch_file
                    })
                    logger.info(f"Found uploaded HLS: {hls_name}")
            
        except Exception as e:
            logger.error(f"Error processing batch file {batch_file}: {e}")
    
    return hls_videos

def update_database_record(connection, original_url, hls_path):
    try:
        cursor = connection.cursor()
        
        # Extract the relative path from original_url
        if "https://staging-static.gokampus.com/" in original_url:
            relative_path = original_url.replace("https://staging-static.gokampus.com/", "")
        else:
            relative_path = os.path.basename(original_url)
        
        # SQL to update the original_content_url and content_url
        query = """
        UPDATE course_lessons 
        SET original_content_url = content_url, 
            content_url = %s 
        WHERE content_url LIKE %s AND deleted_at IS NULL
        """
        
        # Use just the HLS path, not the full URL
        cursor.execute(query, (hls_path, f"%{relative_path}%"))
        rows_affected = cursor.rowcount
        connection.commit()
        
        if rows_affected > 0:
            logger.info(f"Updated {rows_affected} record(s). Original URL: {original_url}, New HLS URL: {hls_path}")
            return True
        else:
            logger.warning(f"No records found for URL: {original_url}")
            return False
            
    except mysql.connector.Error as err:
        logger.error(f"Database error when updating record for {original_url}: {err}")
        return False
    finally:
        if 'cursor' in locals() and cursor is not None:
            cursor.close()

def process_batch_file(connection, batch_files):
    """Mark batch files as processed after all their entries have been handled."""
    uploads_dir = os.getenv('UPLOADS_DIR', 'uploads')
    processed_marker = os.getenv('PROCESSED_MARKER_DIR', os.path.join(uploads_dir, 'processed'))
    
    for batch_file in batch_files:
        batch_name = os.path.basename(batch_file)
        marker_file = os.path.join(processed_marker, f"{batch_name}.processed")
        
        # Create empty marker file to indicate this batch has been processed
        with open(marker_file, 'w') as f:
            f.write(f"Processed on {datetime.now().isoformat()}")
        
        logger.info(f"Marked batch file as processed: {batch_file}")

def main():
    """Main function to check for uploaded videos and update the database."""
    # Check if the required directories exist
    uploads_dir = os.getenv('UPLOADS_DIR', 'uploads')
    if not os.path.exists(uploads_dir):
        logger.error(f"Uploads directory does not exist: {uploads_dir}")
        return
    
    # Find videos that have been successfully uploaded
    logger.info("Checking for successfully uploaded videos...")
    uploaded_videos = find_uploaded_videos()
    
    if not uploaded_videos:
        logger.info("No newly uploaded videos found.")
        return
    
    logger.info(f"Found {len(uploaded_videos)} videos to update in the database.")
    
    # Connect to the database
    connection = connect_to_database()
    if not connection:
        logger.error("Failed to connect to the database. Cannot update records.")
        return
    
    try:
        # Update database records for each uploaded video
        update_count = 0
        processed_batch_files = set()
        
        for video in uploaded_videos:
            original_url = video.get('original_url')
            hls_url = video.get('hls_url')
            
            if update_database_record(connection, original_url, hls_url):
                update_count += 1
                # Remember which batch files we've processed
                if 'batch_file' in video:
                    processed_batch_files.add(video['batch_file'])
        
        # Mark all processed batch files
        process_batch_file(connection, processed_batch_files)
        
        logger.info(f"Successfully updated {update_count}/{len(uploaded_videos)} database records.")
    
    finally:
        # Close the database connection
        if connection:
            connection.close()
            logger.info("Database connection closed")

if __name__ == "__main__":
    while True:
        start_time = datetime.now()
        logger.info(f"Starting URL updater at {start_time}")
        
        main()
        
        end_time = datetime.now()
        duration = end_time - start_time
        logger.info(f"Completed URL updater in {duration}")
        
        # Wait for the next check interval
        check_interval = int(os.getenv('CHECK_INTERVAL', '300'))
        logger.info(f"Waiting {check_interval} seconds before next database check...")
        time.sleep(check_interval)