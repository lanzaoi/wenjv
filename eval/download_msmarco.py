import os
import urllib.request
import tarfile
import time

DATA_DIR = "eval/msmarco_data"

FILES = [
    {
        "url": "https://msmarco.z22.web.core.windows.net/msmarcoranking/qrels.dev.small.tsv",
        "name": "qrels.dev.small.tsv",
        "extract": None,
    },
    {
        "url": "https://msmarco.z22.web.core.windows.net/msmarcoranking/queries.tar.gz",
        "name": "queries.tar.gz",
        "extract": "queries.dev.tsv",
    },
    {
        "url": "https://msmarco.z22.web.core.windows.net/msmarcoranking/collection.tar.gz",
        "name": "collection.tar.gz",
        "extract": "collection.tsv",
    }
]

def download_file(url, target_path):
    print(f"Downloading {url} to {target_path}...")
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req) as response, open(target_path, 'wb') as out_file:
        length = response.getheader('content-length')
        total = int(length) if length else None
        downloaded = 0
        chunk_size = 1024 * 1024 * 5  # 5 MB
        start_time = time.time()
        
        while True:
            chunk = response.read(chunk_size)
            if not chunk:
                break
            out_file.write(chunk)
            downloaded += len(chunk)
            if total:
                percent = downloaded * 100 / total
                speed = downloaded / (1024 * 1024 * (time.time() - start_time + 1e-9))
                print(f"  {percent:.1f}% ({downloaded/(1024*1024):.1f} MB / {total/(1024*1024):.1f} MB) at {speed:.1f} MB/s", end="\r")
            else:
                print(f"  Downloaded {downloaded/(1024*1024):.1f} MB...", end="\r")
        print("\nDownload complete.")

def download_and_extract():
    os.makedirs(DATA_DIR, exist_ok=True)
    for f in FILES:
        file_path = os.path.join(DATA_DIR, f["name"])
        target_path = os.path.join(DATA_DIR, f["extract"]) if f["extract"] else file_path
        
        if os.path.exists(target_path) and os.path.getsize(target_path) > 0:
            print(f"Skipping {target_path}, already exists.")
            continue
            
        download_file(f["url"], file_path)
        
        if file_path.endswith(".tar.gz") and f["extract"]:
            print(f"Extracting {file_path}...")
            with tarfile.open(file_path, "r:gz") as tar:
                for member in tar.getmembers():
                    if member.name.endswith(f["extract"]) or member.name == f["extract"]:
                        member.name = f["extract"]
                        tar.extract(member, path=DATA_DIR)
                        break
            os.remove(file_path)
            print(f"Extracted {f['extract']}")

if __name__ == "__main__":
    download_and_extract()
