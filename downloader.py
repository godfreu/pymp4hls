import requests
import csv
import os
import time

def download_video(csv_file, download_folder):
    """
    Membaca URL video dari file CSV dan mengunduhnya ke folder yang ditentukan.

    Args:
        csv_file: Path ke file CSV.
        download_folder: Path ke folder tempat video akan disimpan.
    """
    if not os.path.exists(download_folder):
        os.makedirs(download_folder)
        print(f"Folder download '{download_folder}' dibuat.")

    try:
        with open(csv_file, 'r', newline='', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            for row in reader:
                content_url = row.get('content_url')
                if content_url:
                    try:
                        response = requests.get(content_url, stream=True)
                        response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)

                        filename = os.path.basename(content_url).split("?")[0]
                        if not filename.lower().endswith(".mp4"):
                            filename += ".mp4"

                        filepath = os.path.join(download_folder, filename)

                        if os.path.exists(filepath):
                            print(f"File '{filename}' sudah ada. Melewati download.")
                            continue


                        with open(filepath, 'wb') as outfile:
                            for chunk in response.iter_content(chunk_size=8192):
                                outfile.write(chunk)
                        print(f"Video '{filename}' berhasil diunduh ke '{download_folder}'")

                    except requests.exceptions.RequestException as e:
                        print(f"Error saat mengunduh dari URL '{content_url}': {e}")

    except FileNotFoundError:
        print(f"Error: File CSV '{csv_file}' tidak ditemukan.")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    csv_file = "/Users/g.e.bayualfian/Documents/GOK/Code/pymp4hls/mp4hls-videos.csv"  # Ganti dengan path yang benar
    download_folder = "/Users/g.e.bayualfian/Documents/GOK/Code/pymp4hls/courses/input"  # Ganti dengan folder input Anda

    while True:
        download_video(csv_file, download_folder)
        print("Menunggu 60 detik sebelum memeriksa CSV lagi...")
        time.sleep(60)