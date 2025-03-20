import requests
import csv
import os
import time

def download_video(csv_file, download_folder, processed_folder):
    if not os.path.exists(download_folder):
        os.makedirs(download_folder)
        print(f"Folder download '{download_folder}' dibuat.")

    if not os.path.exists(processed_folder):
        os.makedirs(processed_folder)
        print(f"Folder processed '{processed_folder}' dibuat.")

    try:
        with open(csv_file, 'r', newline='', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            downloads_performed = False  # Flag untuk melacak apakah ada download
            for row in reader:
                content_url = row.get('content_url')
                if content_url:
                    try:
                        response = requests.get(content_url, stream=True)
                        response.raise_for_status()

                        filename = os.path.basename(content_url).split("?")[0]
                        if not filename.lower().endswith(".mp4"):
                            filename += ".mp4"

                        filepath = os.path.join(download_folder, filename)
                        processed_filepath = os.path.join(processed_folder, filename)

                        if os.path.exists(filepath) or os.path.exists(processed_filepath):
                            print(f"File '{filename}' sudah ada (di input atau processed). Melewati.")
                            continue

                        with open(filepath, 'wb') as outfile:
                            for chunk in response.iter_content(chunk_size=8192):
                                outfile.write(chunk)
                        print(f"Video '{filename}' berhasil diunduh ke '{download_folder}'")
                        downloads_performed = True  # Set flag menjadi True

                    except requests.exceptions.RequestException as e:
                        print(f"Error saat mengunduh dari URL '{content_url}': {e}")

            if not downloads_performed:  # Periksa flag setelah loop
                print("Semua video telah di-download.")


    except FileNotFoundError:
        print(f"Error: File CSV '{csv_file}' tidak ditemukan.")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    csv_file = "/Users/g.e.bayualfian/Documents/GOK/Code/pymp4hls/mp4hls-videos.csv"
    download_folder = "/Users/g.e.bayualfian/Documents/GOK/Code/pymp4hls/courses/input"
    processed_folder = "/Users/g.e.bayualfian/Documents/GOK/Code/pymp4hls/courses/input/processed"

    while True:
        download_video(csv_file, download_folder, processed_folder)
        print("Menunggu 60 detik sebelum memeriksa CSV lagi...")
        time.sleep(60)