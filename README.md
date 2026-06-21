# PyMP4HLS
A complete Python pipeline for fetching, downloading, converting MP4 videos to HTTP Live Streaming (HLS) format, and uploading them to S3 storage, with automatic database updates.

## Features
- **Database Integration**: Automatically fetches video URLs from a MySQL database.
- **URL-Based Downloads**: Downloads videos from URLs specified in CSV files.
- **Automatic Video Processing**: Monitors folders for new videos.
- **Multi-Resolution Output**: Generates multiple quality levels (1080p, 720p, 480p, 360p, 240p).
- **Adaptive Streaming**: Creates HLS playlists for adaptive bitrate streaming.
- **Processed File Management**: Manages CSV batch records and prevents duplicate processing.
- **Cloud Storage**: Uploads processed HLS content to an Amazon S3 bucket.
- **Database Updates**: Updates database records to replace original MP4 paths with new HLS paths.
- **dotenv Support**: All configuration values are loaded via environment variables.

## System Components
1. **URL Scraper (`s1-urlscraper.py`)**  
   - Connects to your MySQL database using credentials from the `.env` file.
   - Fetches new video URLs (using `DB_SELECT_QUERY`), filtering out duplicates by checking existing CSV files.
   - Appends new URLs to the main CSV (`mp4hls-videos.csv`) and creates batch files in the `urls/` folder.

2. **Downloader (`s2-downloader.py`)**  
   - Reads video URLs from the CSV file.
   - Downloads the videos into the `videos/input/` folder.
   - Manages file processing to prevent re-downloading.

3. **Converter (`s3-converter.py`)**  
   - Monitors `videos/input/` for new MP4s.
   - Converts videos to HLS format (generating multi-resolution output).
   - Organizes output in `videos/output/` and moves processed videos to a subfolder.

4. **Uploader (`s4-uploader.py`)**  
   - Scans the `videos/output/` folder for complete HLS directories.
   - Uploads the entire HLS folder (including the master `.m3u8` playlist and all `.ts` segments) to an S3 bucket.
   - Creates batch records (`uploaded-*.csv`) in the `uploads/` folder to log successful uploads.

5. **URL Updater (`s5-urlupdater.py`)**  
   - Reads CSV batch files from the `uploads/` folder.
   - Constructs new HLS paths (e.g., `path/to/hls/hls.m3u8`) based on the HLS directory name.
   - Updates the `course_lessons` table by replacing the original MP4 `content_url` with the new HLS path.
   - Marks batch files as processed to avoid re-updating.

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
- **Windows**: Download from ffmpeg.org (https://ffmpeg.org/download.html)

## Directory Structure
Make sure to create these directories if they do not exist:
``` bash
pymp4hls/
├── videos/
│   ├── input/
│   └── output/
├── logs/
├── urls/
└── uploads/
```
You can create them manually or run:
```bash
mkdir -p videos/input videos/output urls uploads logs
```

## Usage
### Run Setup Once
```bash
./setup.sh
```

### Start Pipeline (Recommended: Agentic Runner)
```bash
./start.sh
```

### Start Legacy Mode (Run s1..s5 Directly)
```bash
./start.sh --legacy
```

### Windows Git Bash Notes
```bash
source venv/Scripts/activate
./start.sh
```

### Stop Running Pipeline Processes
```bash
pkill -f "run_agentic.py|run_tunnel.py|run_pipeline.py|s1-urlscraper.py|s2-downloader.py|s3-converter.py|s4-uploader.py|s5-urlupdater.py"
```

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
RESOLUTIONS=1080,720,480,360,240
CONVERTER_CHECK_INTERVAL=60
DOWNLOADER_CHECK_INTERVAL=60
DOWNLOADER_LONG_INTERVAL=300
CHECK_INTERVAL=300
```

## Customization

- **Resolutions & Bitrates**:  
  Adjust the `RESOLUTIONS` variable in `.env` and tweak functions in `s3-converter.py` as needed.

- **HLS Settings**:  
  Modify FFmpeg flags in `s3-converter.py` (e.g., `-hls_time`) to change segment duration.

- **Database Query**:  
  Customize `DB_SELECT_QUERY` in your `.env` file if your database schema is different.
