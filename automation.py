import os
import subprocess
import glob
import time
import shutil  # Tambahkan ini

def convert_to_hls(input_folder, output_folder, resolutions):

    if not os.path.exists(input_folder):
        print(f"Error: Folder input '{input_folder}' tidak ditemukan.")
        return

    if not os.path.exists(output_folder):
        os.makedirs(output_folder)
        print(f"Folder output '{output_folder}' dibuat.")

    # Buat folder 'processed' jika belum ada
    processed_folder = os.path.join(input_folder, "processed")
    if not os.path.exists(processed_folder):
        os.makedirs(processed_folder)

    mp4_files = glob.glob(os.path.join(input_folder, "*.mp4"))

    if not mp4_files:
        print("Tidak ada file MP4 ditemukan di folder input.")
        return

    for mp4_file in mp4_files:
        basename = os.path.splitext(os.path.basename(mp4_file))[0]
        output_dir = os.path.join(output_folder, basename)
        os.makedirs(output_dir, exist_ok=True)

        print(f"Memproses: {mp4_file}  ->  {output_dir}")

        # ... (sisa kode untuk membuat perintah FFmpeg, filter_complex, dll.) ...
        # 1. BUAT FILTER_COMPLEX STRING
        filter_complex = f"[0:v]split={len(resolutions)}"
        for i in range(len(resolutions)):
            filter_complex += f"[v{i}]"
        filter_complex += ";"

        for i, res in enumerate(resolutions):
            width = int(1920 * (res / 1080))
            if width % 2 != 0:
                width -= 1
            filter_complex += f" [v{i}]scale=w={width}:h={res}[v{i}out];"
        filter_complex = filter_complex[:-1] #hapus ; terakhir

        # 2. BUAT PERINTAH FFMPEG
        ffmpeg_command = [
            "ffmpeg",
            "-i", mp4_file,
            "-filter_complex", filter_complex, # Gunakan filter_complex
            "-profile:v", "baseline",
            "-level", "3.0",
            "-hls_time", "10",
            "-hls_list_size", "0",
            "-f", "hls",

        ]
        # 3. TAMBAHKAN OPSI MAPPING, CODEC, DAN BITRATE
        for i, res in enumerate(resolutions):
            ffmpeg_command.extend([
                f"-map", f"[v{i}out]",
                f"-c:v:{i}", "libx264",
                f"-b:v:{i}", f"{get_bitrate(res)}k",
                 #Tambahan dari command line, untuk memastikan kualitas
                f"-maxrate:v:{i}", f"{int(get_bitrate(res) * 1.07)}k",  # 1.07 = 7% lebih tinggi dari bitrate
                f"-bufsize:v:{i}", f"{int(get_bitrate(res) * 1.5)}k",
            ])
        #Audio streams
        for i, res in enumerate(resolutions):
            ffmpeg_command.extend([
              f"-map", "a:0",
              f"-c:a:{i}", "aac",
              f"-b:a:{i}", f"{get_audio_bitrate(i)}k", # <--- Fungsi get_audio_bitrate
              f"-ac", "2",
            ])

        # 4. OPSI HLS LAINNYA
        master_playlist_path = os.path.join(output_dir, "master.m3u8")

        var_stream_map_str = ""
        for i in range(len(resolutions)):
            var_stream_map_str += f"v:{i},a:{i} "
        var_stream_map_str = var_stream_map_str.strip() # hapus spasi dibelakang


        ffmpeg_command.extend([
            "-hls_segment_filename", os.path.join(output_dir, f"stream_%v/data%03d.ts"),
            "-master_pl_name", "master.m3u8",
            "-var_stream_map", var_stream_map_str,
            f"{output_dir}/stream_%v/playlist.m3u8" # <--- Path playlist relatif thd master
        ])

        try:
            subprocess.run(ffmpeg_command, check=True, capture_output=True, text=True)
            print(f"Konversi selesai: {basename}")

            # Pindahkan file MP4 ke folder 'processed'
            shutil.move(mp4_file, os.path.join(processed_folder, os.path.basename(mp4_file)))
            print(f"File dipindahkan ke: {processed_folder}")


        except subprocess.CalledProcessError as e:
            print(f"Error saat mengonversi {basename}:")
            print(e.stderr)
def get_bitrate(resolution):
    """Bitrate yang lebih rendah."""
    if resolution >= 1080:
        return 5000
    elif resolution >= 720:
        return 2800
    elif resolution >= 480:
        return 1400
    else:
        return 600 # Sesuaikan

def get_audio_bitrate(stream_index): # <--- Fungsi baru
    """Menentukan bitrate audio berdasarkan stream index."""
    if stream_index == 0:
        return 192
    elif stream_index == 1:
        return 128
    else:
        return 96

if __name__ == "__main__":
    input_folder = "/Users/g.e.bayualfian/Documents/GOK/Code/pymp4hls/courses/input"
    output_folder = "/Users/g.e.bayualfian/Documents/GOK/Code/pymp4hls/courses/output"
    resolutions = [1080, 720, 480]

    while True:
      convert_to_hls(input_folder, output_folder, resolutions)
      print("Menunggu 60 detik untuk pengecekan video baru...")
      time.sleep(60)