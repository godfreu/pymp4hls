import os
import subprocess
import glob
import time
import shutil
import logging
import csv
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("logs/s3-converter.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger()

def get_converted_videos(csv_path):
    """
    Read the CSV file containing the list of converted videos.
    Creates the CSV if it doesn't exist.
    
    Returns:
        set: A set of video filenames that have already been converted
    """
    converted_videos = set()
    
    # Create directory if it doesn't exist
    os.makedirs(os.path.dirname(csv_path), exist_ok=True)
    
    # Create the CSV file if it doesn't exist
    if not os.path.exists(csv_path):
        with open(csv_path, 'w', newline='') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(['original_filename', 'hls_name', 'conversion_date', 'status', 'original_deleted'])
        logger.info(f"Created new converted videos CSV: {csv_path}")
        return converted_videos
        
    # Read the existing CSV file
    try:
        df = pd.read_csv(csv_path)
        if not df.empty and 'original_filename' in df.columns:
            converted_videos = set(df['original_filename'].tolist())
        return converted_videos
    except Exception as e:
        logger.error(f"Error reading converted videos CSV: {e}")
        return converted_videos

def add_converted_video(csv_path, original_filename, hls_name, status="success", original_deleted=False):
    """
    Add a newly converted video to the CSV.
    
    Args:
        csv_path: Path to the CSV file
        original_filename: The original video filename
        hls_name: The name of the HLS directory
        status: Conversion status ('success' or 'failed')
        original_deleted: Whether the original file was deleted
    """
    try:
        # Read existing data
        if os.path.exists(csv_path):
            df = pd.read_csv(csv_path)
        else:
            df = pd.DataFrame(columns=['original_filename', 'hls_name', 'conversion_date', 'status', 'original_deleted'])
        
        # Add new entry
        new_row = pd.DataFrame({
            'original_filename': [original_filename],
            'hls_name': [hls_name],
            'conversion_date': [datetime.now().strftime('%Y-%m-%d %H:%M:%S')],
            'status': [status],
            'original_deleted': [original_deleted]
        })
        
        df = pd.concat([df, new_row], ignore_index=True)
        df.to_csv(csv_path, index=False)
        logger.info(f"Added {original_filename} to converted videos CSV")
    except Exception as e:
        logger.error(f"Error adding to converted videos CSV: {e}")

def convert_to_hls(input_folder=None, output_folder=None, resolutions=None):
    # Use environment variables if parameters are not provided
    if input_folder is None:
        input_folder = os.getenv('INPUT_FOLDER', '/pymp4hls/videos/input')
    
    if output_folder is None:
        output_folder = os.getenv('OUTPUT_FOLDER', '/pymp4hls/videos/output')
    
    if resolutions is None:
        resolutions_str = os.getenv('RESOLUTIONS', '1080,720,480, 360, 240')
        resolutions = [int(res) for res in resolutions_str.split(',')]
    
    # Path to the conversions directory and converted videos CSV
    conversions_dir = os.getenv('CONVERSIONS_DIR', 'conversions')
    os.makedirs(conversions_dir, exist_ok=True)
    converted_csv = os.path.join(conversions_dir, 'converted-videos.csv')
    
    # Option to delete original files instead of moving to processed
    delete_originals = os.getenv('DELETE_ORIGINAL_VIDEOS', 'false').lower() == 'true'
    
    # Get the list of already converted videos
    converted_videos = get_converted_videos(converted_csv)
    logger.info(f"Found {len(converted_videos)} previously converted videos")
    
    if not os.path.exists(input_folder):
        logger.error(f"Error: Input folder '{input_folder}' not found.")
        return

    if not os.path.exists(output_folder):
        os.makedirs(output_folder)
        logger.info(f"Output folder '{output_folder}' created.")

    # Create processed folder if it doesn't exist
    processed_folder = os.path.join(input_folder, "processed")
    if not os.path.exists(processed_folder):
        os.makedirs(processed_folder)
        logger.info(f"Processed folder '{processed_folder}' created.")

    video_extensions = ['.mp4', '.mov', '.avi', '.mkv', '.webm', '.flv', '.wmv']
    video_files = []
    for ext in video_extensions:
        video_files.extend(glob.glob(os.path.join(input_folder, f"*{ext}")))

    if not video_files:
        logger.info("No video files found in input folder.")
        return

    for video_file in video_files:
        basename = os.path.splitext(os.path.basename(video_file))[0]
        filename = os.path.basename(video_file)
        
        # Skip if video has already been converted
        if filename in converted_videos:
            logger.info(f"Video {filename} already converted. Skipping.")
            continue
            
        output_dir = os.path.join(output_folder, basename)
        os.makedirs(output_dir, exist_ok=True)

        logger.info(f"Processing: {video_file} -> {output_dir}")
        
        # Check if file has audio before building command
        has_audio = check_for_audio_stream(video_file)
        logger.info(f"File {basename} has audio: {has_audio}")

        # 1. Build filter_complex string
        filter_complex = f"[0:v]split={len(resolutions)}"
        for i in range(len(resolutions)):
            filter_complex += f"[v{i}]"
        filter_complex += ";"

        for i, res in enumerate(resolutions):
            width = int(1920 * (res / 1080))
            if width % 2 != 0:
                width -= 1
            filter_complex += f" [v{i}]scale=w={width}:h={res}[v{i}out];"
        filter_complex = filter_complex.rstrip(';')  # Remove trailing semicolon

        # 2. Build ffmpeg command
        ffmpeg_command = [
            "ffmpeg",
            "-i", video_file,
            "-filter_complex", filter_complex,
            "-profile:v", "baseline",
            "-level", "3.0",
            "-hls_time", "10",
            "-hls_list_size", "0",
            "-f", "hls",
        ]
        
        # 3. Append mapping, codec, and bitrate options
        for i, res in enumerate(resolutions):
            ffmpeg_command.extend([
                "-map", f"[v{i}out]",
                f"-c:v:{i}", "libx264",
                f"-b:v:{i}", f"{get_bitrate(res)}k",
                f"-maxrate:v:{i}", f"{int(get_bitrate(res) * 1.07)}k",
                f"-bufsize:v:{i}", f"{int(get_bitrate(res) * 1.5)}k",
            ])
            
        # Only add audio mappings if the file has audio
        if has_audio:
            for i, res in enumerate(resolutions):
                ffmpeg_command.extend([
                    "-map", "a:0",
                    f"-c:a:{i}", "aac",
                    f"-b:a:{i}", f"{get_audio_bitrate(i)}k",
                    "-ac", "2",
                ])
                
        # 4. Additional HLS options
        master_playlist_name = f"{basename}.m3u8"
        master_playlist_path = os.path.join(output_dir, master_playlist_name)

        # Build var_stream_map differently based on audio availability
        var_stream_map_str = ""
        for i in range(len(resolutions)):
            if has_audio:
                var_stream_map_str += f"v:{i},a:{i} "
            else:
                var_stream_map_str += f"v:{i} "
        var_stream_map_str = var_stream_map_str.strip()  # Remove trailing space
        
        ffmpeg_command.extend([
            "-hls_segment_filename", os.path.join(output_dir, f"stream_%v/data%03d.ts"),
            "-master_pl_name", master_playlist_name,
            "-var_stream_map", var_stream_map_str,
            f"{output_dir}/stream_%v/playlist.m3u8"  # Relative path to master playlist
        ])

        try:
            logger.info(f"Executing FFmpeg command for {basename}: {' '.join(ffmpeg_command)}")
            result = subprocess.run(ffmpeg_command, check=True, capture_output=True, text=True)
            logger.info(f"FFmpeg process completed for: {basename}")
            
            # Verify HLS conversion is complete before handling source file
            if is_hls_conversion_complete(output_dir, basename, resolutions):
                logger.info(f"Conversion successful: {basename}")
                
                # Record successful conversion in CSV
                original_deleted = False
                
                # Handle the original file based on configuration
                if delete_originals:
                    # Delete the original file
                    try:
                        os.remove(video_file)
                        logger.info(f"Deleted original video file: {video_file}")
                        original_deleted = True
                    except Exception as e:
                        logger.error(f"Error deleting original file {video_file}: {e}")
                else:
                    # Move to processed folder
                    try:
                        shutil.move(video_file, os.path.join(processed_folder, filename))
                        logger.info(f"Moved original file to: {processed_folder}")
                    except Exception as e:
                        logger.error(f"Error moving original file {video_file}: {e}")
                
                # Record in CSV after handling the file
                add_converted_video(converted_csv, filename, basename, "success", original_deleted)
                
            else:
                logger.error(f"HLS conversion for {basename} appears incomplete. Original file not touched.")
                # Record failed conversion
                add_converted_video(converted_csv, filename, basename, "failed", False)
            
        except subprocess.CalledProcessError as e:
            logger.error(f"Error converting {basename}:")
            logger.error(e.stderr)
            # Record failed conversion
            add_converted_video(converted_csv, filename, basename, "failed", False)

def get_bitrate(resolution):
    """Return appropriate video bitrate based on resolution."""
    if resolution >= 1080:
        return 5000
    elif resolution >= 720:
        return 2800
    elif resolution >= 480:
        return 1400
    elif resolution >= 360:
        return 800   # adjust as needed
    else:
        return 500   # for 240p

def get_audio_bitrate(stream_index):
    """Determine audio bitrate based on stream index."""
    if stream_index == 0:
        return 192
    elif stream_index == 1:
        return 128
    else:
        return 96

# Add this new function to check for audio streams
def check_for_audio_stream(video_file):
    """Check if the video file has at least one audio stream."""
    try:
        cmd = [
            "ffprobe", 
            "-v", "error", 
            "-select_streams", "a", 
            "-show_entries", "stream=codec_type", 
            "-of", "default=noprint_wrappers=1:nokey=1", 
            video_file
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        return "audio" in result.stdout
    except Exception as e:
        logger.error(f"Error checking for audio stream: {e}")
        # Default to True to avoid breaking existing behavior when probe fails
        return True

def is_hls_conversion_complete(output_dir, basename, resolutions):
    """
    Verify that all expected HLS files exist after conversion.
    """
    try:
        # 1. Check if master playlist exists
        master_playlist = os.path.join(output_dir, f"{basename}.m3u8")
        if not os.path.exists(master_playlist):
            logger.warning(f"Master playlist missing for {basename}")
            return False
            
        # 2. Check each stream directory and its contents
        for i in range(len(resolutions)):
            stream_dir = os.path.join(output_dir, f"stream_{i}")
            
            # Check if stream directory exists
            if not os.path.isdir(stream_dir):
                logger.warning(f"Stream directory stream_{i} missing for {basename}")
                return False
                
            # Check if stream playlist exists
            stream_playlist = os.path.join(stream_dir, "playlist.m3u8")
            if not os.path.exists(stream_playlist):
                logger.warning(f"Stream playlist missing for stream_{i} in {basename}")
                return False
                
            # Check if there are segment files
            segment_files = glob.glob(os.path.join(stream_dir, "*.ts"))
            if not segment_files:
                logger.warning(f"No segment files found for stream_{i} in {basename}")
                return False
                
            # Check playlist references match actual files
            with open(stream_playlist, 'r') as f:
                playlist_content = f.read()
                
            # Count .ts segments referenced in the playlist
            ts_refs = len([line for line in playlist_content.splitlines() if line.endswith(".ts")])
            # Compare with actual .ts files
            if ts_refs != len(segment_files):
                logger.warning(f"Playlist references {ts_refs} segments but found {len(segment_files)} for stream_{i}")
                return False
                
        # All checks passed
        return True
        
    except Exception as e:
        logger.error(f"Error verifying HLS conversion for {basename}: {e}")
        return False

if __name__ == "__main__":
    # Get values from environment variables
    input_folder = os.getenv('INPUT_FOLDER', '/pymp4hls/videos/input')
    output_folder = os.getenv('OUTPUT_FOLDER', '/pymp4hls/videos/output')
    resolutions_str = os.getenv('RESOLUTIONS', '1080,720,480')
    resolutions = [int(res) for res in resolutions_str.split(',')]
    check_interval = int(os.getenv('CONVERTER_CHECK_INTERVAL', '60'))

    logger.info("Starting converter.py")
    logger.info(f"Delete originals mode: {os.getenv('DELETE_ORIGINAL_VIDEOS', 'false')}")
    
    while True:
        convert_to_hls(input_folder, output_folder, resolutions)
        logger.info(f"Waiting {check_interval} seconds for new videos...")
        time.sleep(check_interval)