import os
import glob
import time
import logging
import pandas as pd
import boto3
import shutil  # Add import for directory removal
from botocore.exceptions import ClientError
try:
    from boto3.s3.transfer import S3UploadFailedError
except Exception:
    try:
        from s3transfer.exceptions import S3UploadFailedError  # type: ignore
    except Exception:
        S3UploadFailedError = Exception  # type: ignore
try:
    from google.cloud import storage as gcs_storage
    GCS_AVAILABLE = True
except Exception:
    GCS_AVAILABLE = False
from botocore.config import Config
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
    """Create and return an S3-compatible client (supports GCS endpoint)."""
    try:
        # Endpoint selection (env names cover both AWS and GCS conventions)
        endpoint_url = (
            os.getenv('AWS_ENDPOINT')
            or os.getenv('AWS_ENDPOINT_URL_S3')
            or os.getenv('AWS_ENDPOINT_URL')
        )

        # Defaults from env
        env_region = os.getenv('S3_REGION', 'ap-southeast2')
        explicit_use_path = os.getenv('AWS_USE_PATH_STYLE_ENDPOINT')
        use_path_env = (explicit_use_path or 'false').strip().lower() == 'true'
        addressing_style = 'path' if use_path_env else 'virtual'

        # Smart defaults for GCS endpoints
        region = env_region
        if endpoint_url:
            try:
                from urllib.parse import urlparse
                host = urlparse(endpoint_url).hostname or ''
            except Exception:
                host = ''

            is_gcs = host.endswith('storage.googleapis.com')

            if is_gcs:
                # If global endpoint, prefer region='auto' for signing and path-style unless explicitly overridden
                if host == 'storage.googleapis.com':
                    region = os.getenv('GCS_S3_REGION', 'auto')
                    if explicit_use_path is None:
                        addressing_style = 'path'
                else:
                    # Region-specific endpoint e.g., s3.asia-southeast2.storage.googleapis.com
                    if host.startswith('s3.') and '.storage.googleapis.com' in host:
                        parsed_region = host[len('s3.'):].split('.storage.googleapis.com')[0]
                        if parsed_region:
                            region = parsed_region

        cfg = Config(
            signature_version='s3v4',
            s3={
                'addressing_style': addressing_style,
                'payload_signing_enabled': False,
            },
        )

        s3_client = boto3.client(
            's3',
            aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
            aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
            region_name=region,
            endpoint_url=endpoint_url,
            config=cfg,
        )
        logger.info(
            f"S3-compatible client initialized (region={region}, addressing={addressing_style}) -> "
            f"{endpoint_url or 'AWS default endpoints'}"
        )
        return s3_client
    except Exception as e:
        logger.error(f"Failed to create S3-compatible client: {e}")
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
    # Determine destination bucket/prefix for upload (separate from download bucket)
    bucket_name = None
    prefix_from_gs = None

    # Prefer gs:// style config if provided
    gcs_target = os.getenv('GCP_HLS_BUCKET')
    if gcs_target and gcs_target.startswith('gs://'):
        trimmed = gcs_target[len('gs://'):]
        parts = trimmed.split('/', 2)
        bucket_name = parts[0]
        prefix_from_gs = ''
        if len(parts) > 1:
            prefix_from_gs = parts[1]
            if len(parts) > 2:
                prefix_from_gs = f"{parts[1]}/{parts[2]}"
        prefix_from_gs = prefix_from_gs.strip('/')
        if prefix_from_gs:
            prefix_from_gs += '/'

    # Otherwise use explicit bucket envs for upload (do NOT default to S3_BUCKET_NAME meant for downloads)
    if not bucket_name:
        bucket_name = (
            os.getenv('GCS_BUCKET_NAME')
            or os.getenv('S3_UPLOAD_BUCKET_NAME')
            or os.getenv('HLS_BUCKET_NAME')
            or os.getenv('UPLOAD_BUCKET_NAME')
        )

    if not bucket_name:
        # As a last resort, fall back but warn: this is likely the download bucket
        fallback = os.getenv('S3_BUCKET_NAME')
        if fallback:
            logger.warning(
                "No dedicated upload bucket configured. Falling back to S3_BUCKET_NAME="
                f"{fallback} (this may be intended for downloads)."
            )
            bucket_name = fallback

    if not bucket_name:
        logger.error("No upload bucket configured. Set GCP_HLS_BUCKET (gs://...), GCS_BUCKET_NAME or S3_UPLOAD_BUCKET_NAME.")
        return False

    # Compute prefix
    s3_prefix = prefix_from_gs if prefix_from_gs is not None else os.getenv('S3_PREFIX', 'opt/courses/')
    s3_prefix = s3_prefix.strip('/') + '/'
    base_s3_path = f"{s3_prefix}{hls_name}"
    
    try:
        # Walk through the directory
        for root, dirs, files in os.walk(local_dir):
            for filename in files:
                # Construct local and S3 paths
                local_path = os.path.join(root, filename)
                relative_path = os.path.relpath(local_path, local_dir)

                # Normalize path separators for S3 (replace backslashes with forward slashes)
                relative_path = relative_path.replace('\\', '/')

                s3_path = f"{base_s3_path}/{relative_path}"
                
                # Upload the file
                extra_args = {}
                
                # Set correct content type for different file extensions
                if filename.endswith('.m3u8'):
                    extra_args['ContentType'] = 'application/vnd.apple.mpegurl'
                elif filename.endswith('.ts'):
                    extra_args['ContentType'] = 'video/mp2t'
                
                logger.info(f"Uploading {local_path} to gs://{bucket_name}/{s3_path}")
                s3_client.upload_file(local_path, bucket_name, s3_path, ExtraArgs=extra_args)
                
        # If public URL base is provided (e.g., GCP_LEARNEXT_HLS), show one sample URL for verification
        public_base = os.getenv('GCP_LEARNEXT_HLS')
        if public_base:
            public_base = public_base.rstrip('/') + '/'
            logger.info(f"Sample public URL: {public_base}{hls_name}/{hls_name}.m3u8")

        logger.info(f"Successfully uploaded {hls_name} to Google Cloud Storage (S3-compatible)")
        return True
    except ClientError as e:
        try:
            err = e.response.get('Error', {})
            code = err.get('Code')
            msg = err.get('Message')
            reqid = e.response.get('ResponseMetadata', {}).get('RequestId')
            logger.error(f"Error uploading to S3-compatible storage: {code} - {msg} (RequestId={reqid})")
        except Exception:
            logger.error(f"Error uploading to S3-compatible storage: {e}")
        return False
    except S3UploadFailedError as e:
        # s3transfer wraps ClientError; try to unwrap for details
        cause = getattr(e, '__cause__', None)
        if isinstance(cause, ClientError):
            err = cause.response.get('Error', {})
            code = err.get('Code')
            msg = err.get('Message')
            reqid = cause.response.get('ResponseMetadata', {}).get('RequestId')
            logger.error(f"Upload failed: {code} - {msg} (RequestId={reqid})")
        else:
            logger.error(f"Upload failed: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error during upload: {e}")
        return False

def record_uploaded_batch(hls_name, batch_file):
    """Record a single uploaded HLS entry, appending to current session's CSV."""
    uploads_dir = os.getenv('UPLOADS_DIR', './uploads')
    if not os.path.exists(uploads_dir):
        os.makedirs(uploads_dir)
    
    row = {'hls_name': hls_name, 'upload_time': datetime.now().isoformat()}
    file_exists = os.path.exists(batch_file)
    pd.DataFrame([row]).to_csv(batch_file, mode='a', header=not file_exists, index=False)
    logger.info(f"Recorded upload: {hls_name} -> {batch_file}")

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

def delete_uploaded_hls_directories(output_folder, successful_uploads):
    """
    Delete HLS directories that have been successfully uploaded to S3.
    
    Args:
        output_folder: Path to the output folder containing HLS directories
        successful_uploads: List of HLS directory names that were uploaded
    
    Returns:
        int: Number of successfully deleted directories
    """
    deleted_count = 0
    
    for hls_name in successful_uploads:
        hls_dir = os.path.join(output_folder, hls_name)
        try:
            if os.path.exists(hls_dir) and os.path.isdir(hls_dir):
                shutil.rmtree(hls_dir)
                logger.info(f"Deleted local HLS directory after successful upload: {hls_dir}")
                deleted_count += 1
            else:
                logger.warning(f"HLS directory not found for deletion: {hls_dir}")
        except Exception as e:
            logger.error(f"Error deleting HLS directory {hls_dir}: {e}")
    
    return deleted_count

def parse_gs_target(gs_uri: str):
    """Parse gs://bucket/optional/prefix -> (bucket, prefix_with_trailing_slash_or_empty)"""
    assert gs_uri.startswith('gs://')
    trimmed = gs_uri[len('gs://'):]
    if '/' not in trimmed:
        return trimmed, ''
    first, rest = trimmed.split('/', 1)
    prefix = rest.strip('/')
    if prefix:
        prefix += '/'
    return first, prefix

def upload_directory_to_gcs(local_dir, hls_name):
    """Upload directory to Google Cloud Storage using native client."""
    if not GCS_AVAILABLE:
        logger.error("google-cloud-storage not installed. Please add to requirements and pip install.")
        return False

    gs_target = os.getenv('GCP_HLS_BUCKET')
    bucket_name = None
    base_prefix = None
    if gs_target and gs_target.startswith('gs://'):
        bucket_name, base_prefix = parse_gs_target(gs_target)
    else:
        bucket_name = os.getenv('GCS_BUCKET_NAME') or os.getenv('S3_UPLOAD_BUCKET_NAME') or os.getenv('HLS_BUCKET_NAME')
        base_prefix = (os.getenv('S3_PREFIX', 'opt/courses/').strip('/') + '/')

    if not bucket_name:
        logger.error("No GCS bucket configured. Set GCP_HLS_BUCKET (gs://...), or GCS_BUCKET_NAME.")
        return False

    # Initialize GCS client, prefer explicit service-account JSON from env
    cred_path = os.getenv('GCS_SRV_ACC') or os.getenv('GOOGLE_APPLICATION_CREDENTIALS')
    try:
        if cred_path:
            # Expand and normalize path; support relative paths from CWD
            cred_path_expanded = os.path.expandvars(os.path.expanduser(cred_path))
            if not os.path.isabs(cred_path_expanded):
                cred_path_expanded = os.path.normpath(os.path.join(os.getcwd(), cred_path_expanded))
            if os.path.exists(cred_path_expanded):
                logger.info(f"Using GCS service account credentials from {cred_path_expanded}")
                client = gcs_storage.Client.from_service_account_json(cred_path_expanded)
            else:
                logger.error(f"GCS service account file not found: {cred_path_expanded}")
                return False
        else:
            client = gcs_storage.Client()
    except Exception as e:
        logger.error(f"Failed to initialize GCS client: {e}")
        return False
    bucket = client.bucket(bucket_name)

    try:
        for root, dirs, files in os.walk(local_dir):
            for filename in files:
                local_path = os.path.join(root, filename)
                relative_path = os.path.relpath(local_path, local_dir).replace('\\', '/')
                object_name = f"{base_prefix}{hls_name}/{relative_path}"

                content_type = None
                if filename.endswith('.m3u8'):
                    content_type = 'application/vnd.apple.mpegurl'
                elif filename.endswith('.ts'):
                    content_type = 'video/mp2t'

                logger.info(f"Uploading {local_path} to gs://{bucket_name}/{object_name}")
                blob = bucket.blob(object_name)
                if content_type:
                    blob.content_type = content_type
                blob.upload_from_filename(local_path)

        public_base = os.getenv('GCP_LEARNEXT_HLS')
        if public_base:
            public_base = public_base.rstrip('/') + '/'
            logger.info(f"Sample public URL: {public_base}{hls_name}/{hls_name}.m3u8")
        logger.info(f"Successfully uploaded {hls_name} to Google Cloud Storage (native)")
        return True
    except Exception as e:
        logger.error(f"Unexpected error during GCS upload: {e}")
        return False

def main():
    """Main function to scan output folder and upload HLS files"""
    output_folder = os.getenv('OUTPUT_FOLDER', '/pymp4hls/videos/output')
    delete_after_upload = os.getenv('DELETE_UPLOADED_HLS', 'true').lower() == 'true'
    
    uploaded_hls = get_already_uploaded_hls()
    
    s3_client = get_s3_client()
    if not s3_client:
        logger.error("Failed to create S3-compatible client, aborting upload process")
        return
    
    hls_dirs = []
    for item in os.listdir(output_folder):
        item_path = os.path.join(output_folder, item)
        if os.path.isdir(item_path):
            if is_hls_conversion_complete(item_path):
                hls_dirs.append(item)
            else:
                logger.info(f"Skipping incomplete HLS directory: {item}")
    
    if not hls_dirs:
        logger.info("No HLS directories found for upload")
        return
    
    logger.info(f"Found {len(hls_dirs)} potential HLS directories for upload")
    
    new_hls_dirs = [hls for hls in hls_dirs if hls not in uploaded_hls]
    
    if not new_hls_dirs:
        logger.info("All HLS directories have already been uploaded")
        return
    
    logger.info(f"{len(new_hls_dirs)} new HLS directories to upload")
    
    # ✅ Definisikan use_native_gcs SEBELUM loop
    use_native_gcs = (os.getenv('GCP_HLS_BUCKET') is not None) or (os.getenv('USE_GCS_NATIVE', 'false').lower() == 'true')

    # Tentukan batch file untuk sesi ini sebelum loop
    uploads_dir = os.getenv('UPLOADS_DIR', './uploads')
    current_batch_file = os.path.join(uploads_dir, f"uploaded-{get_next_batch_number()}.csv")

    successful_uploads = []
    total_deleted = 0
    for hls_name in new_hls_dirs:
        local_dir = os.path.join(output_folder, hls_name)
        if is_hls_conversion_complete(local_dir):
            ok = False
            if use_native_gcs:
                ok = upload_directory_to_gcs(local_dir, hls_name)
            else:
                ok = upload_directory_to_s3(s3_client, local_dir, hls_name)
            if ok:
                successful_uploads.append(hls_name)
                # ✅ Catat ke CSV segera setelah upload berhasil
                record_uploaded_batch(hls_name, current_batch_file)
                # ✅ Lalu langsung delete
                if delete_after_upload:
                    deleted = delete_uploaded_hls_directories(output_folder, [hls_name])
                    total_deleted += deleted
                    if deleted:
                        logger.info(f"Freed disk space after uploading {hls_name}")

    if delete_after_upload:
        logger.info(f"Deleted {total_deleted} of {len(successful_uploads)} local HLS directories")
    logger.info(f"Upload process completed. {len(successful_uploads)} of {len(new_hls_dirs)} directories uploaded successfully.")

if __name__ == "__main__":
    # Log the delete setting when starting
    delete_setting = os.getenv('DELETE_UPLOADED_HLS', 'true').lower() == 'true'
    logger.info(f"Starting uploader (S3-compatible) (Delete uploaded HLS: {delete_setting})")
    
    while True:
        start_time = datetime.now()
        logger.info(f"Starting uploader at {start_time}")
        
        main()
        
        end_time = datetime.now()
        duration = end_time - start_time
        logger.info(f"Completed uploader in {duration}")
        
        # Wait before next check
        check_interval = int(os.getenv('CHECK_INTERVAL', 300))  # Default 5 minutes
        logger.info(f"Waiting {check_interval} seconds before next check...")

        # Optional one-shot mode
        run_once = os.getenv('RUN_ONCE', '').strip().lower() in ('1', 'true', 'yes', 'y')
        if run_once:
            logger.info("RUN_ONCE detected — exiting after first cycle.")
            break

        time.sleep(check_interval)

