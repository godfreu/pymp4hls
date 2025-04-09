import os
import subprocess
import glob
import time
import shutil
import logging
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

def convert_to_hls(input_folder=None, output_folder=None, resolutions=None):
    # Use environment variables if parameters are not provided
    if input_folder is None:
        input_folder = os.getenv('INPUT_FOLDER', '/pymp4hls/videos/input')
    
    if output_folder is None:
        output_folder = os.getenv('OUTPUT_FOLDER', '/pymp4hls/videos/output')
    
    if resolutions is None:
        resolutions_str = os.getenv('RESOLUTIONS', '1080,720,480')
        resolutions = [int(res) for res in resolutions_str.split(',')]
    
    if not os.path.exists(input_folder):
        logger.error(f"Error: Folder input '{input_folder}' tidak ditemukan.")
        return

    if not os.path.exists(output_folder):
        os.makedirs(output_folder)
        logger.info(f"Folder output '{output_folder}' dibuat.")

    # Create processed folder if it doesn't exist
    processed_folder = os.path.join(input_folder, "processed")
    if not os.path.exists(processed_folder):
        os.makedirs(processed_folder)
        logger.info(f"Processed folder '{processed_folder}' dibuat.")

    video_extensions = ['.mp4', '.mov', '.avi', '.mkv', '.webm', '.flv', '.wmv']
    video_files = []
    for ext in video_extensions:
        video_files.extend(glob.glob(os.path.join(input_folder, f"*{ext}")))

    if not video_files:
        logger.info("No video files found in input folder.")
        return

    for video_file in video_files:
        basename = os.path.splitext(os.path.basename(video_file))[0]
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
        filter_complex = filter_complex.rstrip(';')  # Remove the trailing semicolon

        # 2. Build ffmpeg command
        ffmpeg_command = [
            "ffmpeg",
            "-i", video_file,
            "-filter_complex", filter_complex,  # Use filter_complex
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
            
            # Verify HLS conversion is complete before moving source file
            if is_hls_conversion_complete(output_dir, basename, resolutions):
                logger.info(f"Konversi selesai: {basename}")
                # Move processed video file only when conversion is verified
                shutil.move(video_file, os.path.join(processed_folder, os.path.basename(video_file)))
                logger.info(f"File {video_file} moved to: {processed_folder}")
            else:
                logger.error(f"HLS conversion for {basename} appears incomplete. Original file not moved.")
            
        except subprocess.CalledProcessError as e:
            logger.error(f"Error saat mengonversi {basename}:")
            logger.error(e.stderr)

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
    while True:
        convert_to_hls(input_folder, output_folder, resolutions)
        logger.info(f"Menunggu {check_interval} detik untuk pengecekan video baru...")
        time.sleep(check_interval)