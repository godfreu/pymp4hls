import os
import glob
import time
import logging
import pandas as pd
import boto3
from botocore.exceptions import ClientError
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("logs/s4-uploader.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger()

def get_s3_client():
    """Create and return an S3 client"""
    try:
        s3_client = boto3.client(
            's3',
            aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
            aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
            region_name=os.getenv('S3_REGION', 'us-east-1')
        )
        return s3_client
    except Exception as e:
        logger.error(f"Failed to create S3 client: {e}")
        return None

def get_already_uploaded_hls():
    """Get a list of HLS names that have already been uploaded to S3"""
    uploaded_hls = set()
    
    # Ensure uploads directory exists
    uploads_dir = os.getenv('UPLOADS_DIR', '/pymp4hls/uploads')
    if not os.path.exists(uploads_dir):
        os.makedirs(uploads_dir)
        logger.info(f"Created directory {uploads_dir}")
    
    # Read all upload batch files
    batch_files = glob.glob(os.path.join(uploads_dir, "uploaded-*.csv"))
    for batch_file in batch_files:
        try:
            df = pd.read_csv(batch_file)
            if 'hls_name' in df.columns:
                uploaded_hls.update(df['hls_name'].tolist())
        except Exception as e:
            logger.error(f"Error reading batch file {batch_file}: {e}")
    
    logger.info(f"Found {len(uploaded_hls)} already uploaded HLS directories")
    return uploaded_hls

def get_next_batch_number():
    """Find the next available batch number for upload tracking"""
    uploads_dir = os.getenv('UPLOADS_DIR', '/pymp4hls/uploads')
    batch_files = glob.glob(os.path.join(uploads_dir, "uploaded-*.csv"))
    if not batch_files:
        return 1
        
    batch_numbers = []
    for file in batch_files:
        try:
            batch_num = int(file.split('-')[-1].split('.')[0])
            batch_numbers.append(batch_num)
        except (ValueError, IndexError):
            continue
            
    return max(batch_numbers) + 1 if batch_numbers else 1

def upload_directory_to_s3(s3_client, local_dir, hls_name):
    """
    Upload an entire directory structure to S3
    Returns True if successful, False otherwise
    """
    bucket_name = os.getenv('S3_BUCKET_NAME')
    if not bucket_name:
        logger.error("S3_BUCKET_NAME not set in environment variables")
        return False
        
    s3_prefix = os.getenv('S3_PREFIX', 'opt/courses/')
    base_s3_path = f"{s3_prefix}{hls_name}"
    
    try:
        # Walk through the directory
        for root, dirs, files in os.walk(local_dir):
            for filename in files:
                # Construct local and S3 paths
                local_path = os.path.join(root, filename)
                relative_path = os.path.relpath(local_path, local_dir)  # Calculate relative to local_dir itself
                s3_path = f"{base_s3_path}/{relative_path}"
                
                # Upload the file
                extra_args = {}
                
                # Set correct content type for different file extensions
                if filename.endswith('.m3u8'):
                    extra_args['ContentType'] = 'application/vnd.apple.mpegurl'
                elif filename.endswith('.ts'):
                    extra_args['ContentType'] = 'video/mp2t'
                
                logger.info(f"Uploading {local_path} to s3://{bucket_name}/{s3_path}")
                s3_client.upload_file(local_path, bucket_name, s3_path, ExtraArgs=extra_args)
                
        logger.info(f"Successfully uploaded {hls_name} to S3")
        return True
    except ClientError as e:
        logger.error(f"Error uploading to S3: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error during upload: {e}")
        return False

def record_uploaded_batch(uploaded_hls_list):
    """Record successfully uploaded HLS directories to a batch CSV file"""
    if not uploaded_hls_list:
        return None
        
    uploads_dir = os.getenv('UPLOADS_DIR', '/pymp4hls/uploads')
    if not os.path.exists(uploads_dir):
        os.makedirs(uploads_dir)
    
    batch_num = get_next_batch_number()
    batch_file = os.path.join(uploads_dir, f"uploaded-{batch_num}.csv")
    
    # Create DataFrame and save to CSV
    data = {'hls_name': uploaded_hls_list, 'upload_time': [datetime.now().isoformat()] * len(uploaded_hls_list)}
    df = pd.DataFrame(data)
    df.to_csv(batch_file, index=False)
    
    logger.info(f"Created upload record batch #{batch_num} with {len(uploaded_hls_list)} items in {batch_file}")
    return batch_num

def is_hls_conversion_complete(hls_dir):
    """
    Check if an HLS directory is fully converted and ready for upload
    by verifying all expected files are present.
    """
    master_playlist = os.path.join(hls_dir, f"{os.path.basename(hls_dir)}.m3u8")
    
    # 1. Check master playlist exists
    if not os.path.exists(master_playlist):
        logger.info(f"Master playlist missing for {os.path.basename(hls_dir)}")
        return False
        
    # 2. Read master playlist to check for expected streams
    try:
        with open(master_playlist, 'r') as f:
            content = f.read()
            
        # 3. Make sure the master playlist references stream directories
        stream_refs = [line for line in content.splitlines() if "stream_" in line]
        if not stream_refs:
            logger.info(f"No stream references found in master playlist for {os.path.basename(hls_dir)}")
            return False
            
        # 4. Check each referenced stream directory exists and has content
        for stream_ref in stream_refs:
            # Extract stream path from playlist line
            stream_path = stream_ref.split('/')[-2]  # Assumes format like: stream_0/playlist.m3u8
            stream_dir = os.path.join(hls_dir, stream_path)
            
            if not os.path.isdir(stream_dir):
                logger.info(f"Stream directory {stream_path} missing for {os.path.basename(hls_dir)}")
                return False
                
            # 5. Check stream has a playlist
            stream_playlist = os.path.join(stream_dir, "playlist.m3u8")
            if not os.path.exists(stream_playlist):
                logger.info(f"Stream playlist missing for {stream_path} in {os.path.basename(hls_dir)}")
                return False
                
            # 6. Check stream has segment files
            segment_files = glob.glob(os.path.join(stream_dir, "*.ts"))
            if not segment_files:
                logger.info(f"No segment files found for {stream_path} in {os.path.basename(hls_dir)}")
                return False
                
            # 7. Check stream playlist references the segment files that exist
            with open(stream_playlist, 'r') as f:
                playlist_content = f.read()
                
            # Count .ts segments referenced in the playlist
            ts_refs = len([line for line in playlist_content.splitlines() if line.endswith(".ts")])
            # Compare with actual .ts files
            if ts_refs != len(segment_files):
                logger.info(f"Playlist references {ts_refs} segments but found {len(segment_files)} for {stream_path}")
                return False
        
        # 8. If we passed all checks, the HLS directory is complete
        return True
        
    except Exception as e:
        logger.error(f"Error validating HLS directory {os.path.basename(hls_dir)}: {e}")
        return False

def main():
    """Main function to scan output folder and upload HLS files"""
    # Get configuration from environment variables
    output_folder = os.getenv('OUTPUT_FOLDER', '/pymp4hls/videos/output')
    
    # Get list of already uploaded HLS
    uploaded_hls = get_already_uploaded_hls()
    
    # Get S3 client
    s3_client = get_s3_client()
    if not s3_client:
        logger.error("Failed to create S3 client, aborting upload process")
        return
    
    # Scan output folder for HLS directories
    hls_dirs = []
    for item in os.listdir(output_folder):
        item_path = os.path.join(output_folder, item)
        if os.path.isdir(item_path):
            # Check if this is a complete HLS directory
            if is_hls_conversion_complete(item_path):
                hls_dirs.append(item)
            else:
                logger.info(f"Skipping incomplete HLS directory: {item}")
    
    if not hls_dirs:
        logger.info("No HLS directories found for upload")
        return
    
    logger.info(f"Found {len(hls_dirs)} potential HLS directories for upload")
    
    # Filter out already uploaded HLS
    new_hls_dirs = [hls for hls in hls_dirs if hls not in uploaded_hls]
    
    if not new_hls_dirs:
        logger.info("All HLS directories have already been uploaded")
        return
    
    logger.info(f"{len(new_hls_dirs)} new HLS directories to upload")
    
    # Upload each new HLS directory
    successful_uploads = []
    for hls_name in new_hls_dirs:
        local_dir = os.path.join(output_folder, hls_name)
        if is_hls_conversion_complete(local_dir) and upload_directory_to_s3(s3_client, local_dir, hls_name):
            successful_uploads.append(hls_name)
    
    # Record successfully uploaded HLS
    if successful_uploads:
        record_uploaded_batch(successful_uploads)
    
    logger.info(f"Upload process completed. {len(successful_uploads)} of {len(new_hls_dirs)} directories uploaded successfully.")

if __name__ == "__main__":
    while True:
        start_time = datetime.now()
        logger.info(f"Starting S3 uploader at {start_time}")
        
        main()
        
        end_time = datetime.now()
        duration = end_time - start_time
        logger.info(f"Completed S3 uploader in {duration}")
        
        # Wait before next check
        check_interval = int(os.getenv('CHECK_INTERVAL', 300))  # Default 5 minutes
        logger.info(f"Waiting {check_interval} seconds before next check...")
        time.sleep(check_interval)