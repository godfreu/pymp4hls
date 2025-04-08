# PyMP4HLS

A complete Python pipeline for fetching, downloading, converting MP4 videos to HTTP Live Streaming (HLS) format, and uploading to S3 storage.

## Features

- **Database Integration**: Automatically fetches video URLs from a MySQL database.
- **URL-Based Downloads**: Downloads videos from URLs specified in CSV files.
- **Automatic Video Processing**: Monitors folders for new videos.
- **Multi-Resolution Output**: Generates multiple quality levels (1080p, 720p, 480p by default).
- **Adaptive Streaming**: Creates HLS playlists for adaptive bitrate streaming.
- **Processed File Management**: Automatically moves processed files to prevent reprocessing.
- **Cloud Storage**: Uploads processed HLS content to an Amazon S3 bucket.
- **Duplicate Prevention**: Maintains batch records to ensure no URL is processed twice.
- **dotenv Support**: All configuration values are loaded via environment variables.

## System Components

1. **URL Scraper** (`urlscraper.py`):  
   Fetches video URLs from the database and appends new entries to:
   - The primary CSV file (`mp4hls-videos.csv`)
   - Batch files in the `urls/` folder (e.g., `urlscrapped_batch-1.csv`)

2. **Downloader** (`downloader.py`):  
   Reads URLs from the CSV file, downloads videos to the input folder, and manages processed file tracking.

3. **Converter** (`converter.py`):  
   Monitors the input folder, converts MP4s to multi-resolution HLS using FFmpeg, and moves processed videos.

4. **Uploader** (`uploader.py`):  
   Scans the output folder for HLS directories, uploads the content to an S3 bucket, and creates batch records (e.g., `uploaded-1.csv`) in the `uploads/` folder.

## Requirements

- **Python 3.10-3.12** (3.12.x recommended)
- **FFmpeg** (must be installed on your system)
- **MySQL Database** (for URL scraping)
- **AWS S3 Bucket** (for uploading HLS content)
- Python packages (listed in [requirements.txt](./requirements.txt)):
  - requests
  - pandas
  - mysql-connector-python
  - python-dotenv
  - boto3

## Installation

### 1. Clone the Repository
```bash
git clone https://github.com/godfreu/pymp4hls.git
cd pymp4hls
```

### 2. Create and Activate a Virtual Environment
```bash
python -m venv venv
source venv/bin/activate
```
*Your prompt should now display `(venv)`. After finished working: $ deactivate*

### 3. Install Dependencies
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Configure Environment Variables
Create a `.env` file based on the provided `.env.example`:
```bash
cp .env.example .env
nano .env
```
*Edit the file to include your database credentials, file paths, S3 settings, etc.*

### 5. Ensure FFmpeg is Installed
- **macOS**: `brew install ffmpeg`
- **Ubuntu/Debian**: `sudo apt install ffmpeg`
- **Windows**: Download from [ffmpeg.org](https://ffmpeg.org/download.html)

## Directory Structure

Make sure to create these directories if they do not exist:
```
pymp4hls/
├── videos/
│   ├── input/
│   └── output/
├── urls/
└── uploads/
```
You can create them manually or run:
```bash
mkdir -p videos/input videos/output urls uploads
```

## Usage

### 1. Run URL Scraper
Fetch video URLs from your database (without updating their status) and record them:
```bash
python urlscraper.py
```

### 2. Run Downloader
Download videos from the URLs in the CSV:
```bash
python downloader.py
```

### 3. Run Converter
Convert downloaded videos to HLS:
```bash
python converter.py
```

### 4. Run Uploader
Upload HLS output to the S3 bucket:
```bash
python uploader.py
```

## How It Works

1. **URL Scraping**:  
   `urlscraper.py`:
   - Connects to your MySQL database using credentials from `.env`.
   - Fetches video URLs (using `DB_SELECT_QUERY`) that are pending.
   - Checks existing CSV files (main and batched) to avoid duplicates.
   - Writes new URLs into `mp4hls-videos.csv` and creates a batch file in the `urls/` folder.

2. **Downloading** (`downloader.py`):  
   Reads from `mp4hls-videos.csv` and downloads videos to the `videos/input/` folder.

3. **Converting** (`converter.py`):  
   Monitors `videos/input/` for new MP4s, converts them using FFmpeg, and moves the originals to a `processed` subfolder.

4. **Uploading** (`uploader.py`):  
   Scans `videos/output/` for complete HLS directories, uploads them to S3, and then logs the upload in a batch CSV file in the `uploads/` folder.

## Environment Variables Example
Below is an example of the configuration in your `.env` file:
```bash
# Database Configuration
DB_HOST=localhost
DB_USER=your_username
DB_PASSWORD=your_password
DB_NAME=your_database
DB_SELECT_QUERY=SELECT video_url FROM videos WHERE status = 'pending' LIMIT 10

# File Paths
MAIN_CSV_PATH=/path/to/pymp4hls/mp4hls-videos.csv
URLS_DIR=/path/to/pymp4hls/urls
INPUT_FOLDER=/path/to/pymp4hls/videos/input
OUTPUT_FOLDER=/path/to/pymp4hls/videos/output
UPLOADS_DIR=/path/to/pymp4hls/uploads

# S3 Configuration
AWS_ACCESS_KEY_ID=your_access_key
AWS_SECRET_ACCESS_KEY=your_secret_key
S3_BUCKET_NAME=your-bucket-name
S3_REGION=us-east-1
S3_PREFIX=hls/

# Application Settings
RESOLUTIONS=1080,720,480
CONVERTER_CHECK_INTERVAL=60
DOWNLOADER_CHECK_INTERVAL=60
DOWNLOADER_LONG_INTERVAL=300
UPLOAD_CHECK_INTERVAL=300
```

## Customization

- **Resolutions & Bitrates**:  
  Adjust the `RESOLUTIONS` variable in `.env` and tweak functions in `converter.py` as needed.

- **HLS Settings**:  
  Modify FFmpeg flags in `converter.py` (e.g., `-hls_time`) to change segment duration.

- **Database Query**:  
  Customize `DB_SELECT_QUERY` in your `.env` file if your database schema is different.

## License

[Specify your License Here]

---

This README.md now provides clear setup and usage instructions while ensuring that all configuration is handled by dotenv.