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

def download_video(csv_file=None, download_folder=None, processed_folder=None):
    # Use environment variables if parameters are not provided
    if csv_file is None:
        csv_file = os.getenv('MAIN_CSV_PATH', '/pymp4hls/mp4hls-videos.csv')
    
    if download_folder is None:
        download_folder = os.getenv('INPUT_FOLDER', '/pymp4hls/videos/input')
    
    if processed_folder is None:
        processed_folder = os.path.join(download_folder, "processed")

    if not os.path.exists(download_folder):
        os.makedirs(download_folder)
        logger.info(f"Folder download '{download_folder}' dibuat.")

    if not os.path.exists(processed_folder):
        os.makedirs(processed_folder)
        logger.info(f"Folder processed '{processed_folder}' dibuat.")

    try:
        # Read the CSV file with pandas for easier manipulation
        df = pd.read_csv(csv_file)
        if df.empty:
            logger.info("CSV file is empty. No videos to download.")
            return False
            
        downloads_performed = False  # Flag untuk melacak apakah ada download
        
        # Create a list to track rows to remove
        rows_to_remove = []
        
        for index, row in df.iterrows():
            content_url = row.get('content_url')
            if content_url:
                try:
                    filename = os.path.basename(content_url).split("?")[0]
                    if not filename.lower().endswith(".mp4"):
                        filename += ".mp4"
                    
                    filepath = os.path.join(download_folder, filename)
                    processed_filepath = os.path.join(processed_folder, filename)

                    if os.path.exists(filepath) or os.path.exists(processed_filepath):
                        logger.info(f"File '{filename}' sudah ada (di input atau processed). Melewati.")
                        # Add to rows to remove since it's already processed
                        rows_to_remove.append(index)
                        continue

                    logger.info(f"Downloading video: {content_url}")
                    response = requests.get(content_url, stream=True)
                    response.raise_for_status()

                    with open(filepath, 'wb') as outfile:
                        for chunk in response.iter_content(chunk_size=8192):
                            outfile.write(chunk)
                    logger.info(f"Video '{filename}' berhasil diunduh ke '{download_folder}'")
                    downloads_performed = True
                    
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