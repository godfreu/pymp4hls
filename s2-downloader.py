import requests
import csv
import os
import time
import pandas as pd
import shutil
import logging
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("logs/s2-downloader.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger()

def get_file_extension_from_headers(url):
    """Determine file extension based on Content-Type header"""
    try:
        response = requests.head(url, timeout=5)
        content_type = response.headers.get('Content-Type', '')
        
        # Map content types to file extensions
        content_type_map = {
            'video/mp4': '.mp4',
            'video/quicktime': '.mov',
            'video/x-msvideo': '.avi',
            'video/x-matroska': '.mkv',
            'video/webm': '.webm',
            'video/x-flv': '.flv',
            'video/x-ms-wmv': '.wmv'
        }
        
        for mime, ext in content_type_map.items():
            if mime in content_type:
                return ext
                
        return None
    except Exception as e:
        logger.error(f"Error getting content type: {e}")
        return None

def get_downloaded_videos(csv_path):
    """
    Read the CSV file containing the list of downloaded videos.
    Creates the CSV if it doesn't exist.
    
    Returns:
        set: A set of video URLs that have already been downloaded
    """
    downloaded_videos = set()
    
    # Create directory if it doesn't exist
    os.makedirs(os.path.dirname(csv_path), exist_ok=True)
    
    # Create the CSV file if it doesn't exist
    if not os.path.exists(csv_path):
        with open(csv_path, 'w', newline='') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(['content_url', 'filename', 'download_date'])
        logger.info(f"Created new downloaded videos CSV: {csv_path}")
        return downloaded_videos
        
    # Read the existing CSV file
    try:
        df = pd.read_csv(csv_path)
        if not df.empty and 'content_url' in df.columns:
            downloaded_videos = set(df['content_url'].tolist())
        return downloaded_videos
    except Exception as e:
        logger.error(f"Error reading downloaded videos CSV: {e}")
        return downloaded_videos

def add_downloaded_video(csv_path, content_url, filename):
    """
    Add a newly downloaded video to the CSV.
    
    Args:
        csv_path: Path to the CSV file
        content_url: The URL of the downloaded video
        filename: The filename the video was saved as
    """
    try:
        # Read existing data
        if os.path.exists(csv_path):
            df = pd.read_csv(csv_path)
        else:
            df = pd.DataFrame(columns=['content_url', 'filename', 'download_date'])
        
        # Add new entry
        new_row = pd.DataFrame({
            'content_url': [content_url],
            'filename': [filename],
            'download_date': [datetime.now().strftime('%Y-%m-%d %H:%M:%S')]
        })
        
        df = pd.concat([df, new_row], ignore_index=True)
        df.to_csv(csv_path, index=False)
        logger.info(f"Added {filename} to downloaded videos CSV")
    except Exception as e:
        logger.error(f"Error adding to downloaded videos CSV: {e}")

def download_video(csv_file=None, download_folder=None, processed_folder=None):
    # Use environment variables if parameters are not provided
    if csv_file is None:
        csv_file = os.getenv('MAIN_CSV_PATH', '/pymp4hls/mp4hls-videos.csv')
    
    if download_folder is None:
        download_folder = os.getenv('INPUT_FOLDER', '/pymp4hls/videos/input')
    
    if processed_folder is None:
        processed_folder = os.path.join(download_folder, "processed")

    # Path to the downloads directory and downloaded videos CSV
    downloads_dir = os.getenv('DOWNLOADS_DIR', 'downloads')
    downloaded_csv = os.path.join(downloads_dir, 'downloaded-videos.csv')

    # Create necessary directories
    if not os.path.exists(download_folder):
        os.makedirs(download_folder)
        logger.info(f"Folder download '{download_folder}' dibuat.")

    if not os.path.exists(processed_folder):
        os.makedirs(processed_folder)
        logger.info(f"Folder processed '{processed_folder}' dibuat.")

    try:
        # Get the list of already downloaded videos
        downloaded_videos = get_downloaded_videos(downloaded_csv)
        logger.info(f"Found {len(downloaded_videos)} previously downloaded videos")
        
        # Read the CSV file with pandas for easier manipulation
        df = pd.read_csv(csv_file)
        if df.empty:
            logger.info("CSV file is empty. No videos to download.")
            return False
            
        downloads_performed = False  # Flag to track if any downloads occurred
        
        # Create a list to track rows to remove
        rows_to_remove = []
        
        for index, row in df.iterrows():
            content_url = row.get('content_url')
            if content_url:
                # Check if this URL has already been downloaded
                if content_url in downloaded_videos:
                    logger.info(f"Video already downloaded: {content_url}. Skipping.")
                    rows_to_remove.append(index)
                    continue
                    
                try:
                    # Extract filename from URL and remove query parameters
                    filename = os.path.basename(content_url).split("?")[0]
                    
                    # Check if filename has a recognized video extension
                    valid_extensions = ['.mp4', '.mov', '.avi', '.mkv', '.webm', '.flv', '.wmv']
                    has_valid_extension = any(filename.lower().endswith(ext) for ext in valid_extensions)
                    
                    if not has_valid_extension:
                        ext = get_file_extension_from_headers(content_url)
                        if ext:
                            filename += ext
                        elif 'mp4' in content_url.lower():
                            filename += '.mp4'
                        else:
                            logger.warning(f"Could not determine file type for {content_url}, defaulting to .mp4")
                            filename += '.mp4'
                    
                    filepath = os.path.join(download_folder, filename)

                    logger.info(f"Downloading video: {content_url}")
                    response = requests.get(content_url, stream=True)
                    response.raise_for_status()

                    with open(filepath, 'wb') as outfile:
                        for chunk in response.iter_content(chunk_size=8192):
                            outfile.write(chunk)
                    
                    logger.info(f"Video '{filename}' berhasil diunduh ke '{download_folder}'")
                    downloads_performed = True
                    
                    # Add to downloaded videos CSV
                    add_downloaded_video(downloaded_csv, content_url, filename)
                    
                    # Add this row to the list of rows to remove
                    rows_to_remove.append(index)

                except requests.exceptions.RequestException as e:
                    logger.error(f"Error saat mengunduh dari URL '{content_url}': {e}")

        # Remove processed rows and save the CSV
        if rows_to_remove:
            df = df.drop(rows_to_remove)
            df.to_csv(csv_file, index=False)
            logger.info(f"Removed {len(rows_to_remove)} processed entries from CSV file")
            
        if not downloads_performed and len(rows_to_remove) == 0:
            logger.info("Semua video telah di-download.")
            return False
        
        return True

    except FileNotFoundError:
        logger.error(f"Error: File CSV '{csv_file}' tidak ditemukan.")
        return False
    except Exception as e:
        logger.error(f"Error: {e}")
        return False


if __name__ == "__main__":
    csv_file = os.getenv('MAIN_CSV_PATH', '/pymp4hls/mp4hls-videos.csv')
    download_folder = os.getenv('INPUT_FOLDER', '/pymp4hls/videos/input')
    processed_folder = os.path.join(download_folder, "processed")
    check_interval = int(os.getenv('DOWNLOADER_CHECK_INTERVAL', '60'))
    long_interval = int(os.getenv('DOWNLOADER_LONG_INTERVAL', '300'))

    while True:
        result = download_video(csv_file, download_folder, processed_folder)
        wait_time = check_interval if result else long_interval
        logger.info(f"Menunggu {wait_time} detik sebelum memeriksa CSV lagi...")
        time.sleep(wait_time)