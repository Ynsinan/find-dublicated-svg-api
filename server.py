from flask import Flask, request, jsonify
import os
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
import itertools
import base64
import cairosvg
import cv2
from skimage.metrics import structural_similarity as ssim
from colorama import init, Fore, Style
import uuid
import numpy as np
from flask_cors import cross_origin
import time
import hashlib
from collections import defaultdict
import gzip
import io

# Initialize colorama
init()

app = Flask(__name__)
UPLOAD_FOLDER = 'uploaded_svgs'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Konfigürasyon
MAX_FILES = 100  # Maksimum dosya sayısı
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB
BATCH_SIZE = 50  # Batch işleme için
TIMEOUT_SECONDS = 300  # 5 dakika timeout
MAX_WORKERS = min(8, os.cpu_count())  # CPU çekirdek sayısına göre ayarla

def get_file_hash(file_content):
    """Dosya hash'i hesapla - aynı dosyaları hızlıca tespit etmek için"""
    return hashlib.md5(file_content).hexdigest()

def quick_duplicate_check(files_data):
    """Hash tabanlı hızlı duplikasyon kontrolü"""
    hash_groups = defaultdict(list)
    
    for filename, content in files_data.items():
        file_hash = get_file_hash(content)
        hash_groups[file_hash].append(filename)
    
    # Aynı hash'e sahip dosyalar kesinlikle duplikat
    exact_duplicates = []
    for file_group in hash_groups.values():
        if len(file_group) > 1:
            for i in range(len(file_group)):
                for j in range(i + 1, len(file_group)):
                    exact_duplicates.append((file_group[i], file_group[j]))
    
    return exact_duplicates, hash_groups

def svg_to_png_optimized(svg_content, max_size=200):
    """SVG'yi optimize edilmiş PNG'ye çevir"""
    try:
        png_output = io.BytesIO()
        cairosvg.svg2png(
            bytestring=svg_content, 
            write_to=png_output,
            output_width=max_size,
            output_height=max_size
        )
        png_output.seek(0)
        return png_output.getvalue()
    except Exception as e:
        print(Fore.RED + f"Error processing SVG: {e}" + Style.RESET_ALL)
        return None

def compare_images_fast(img1_bytes, img2_bytes):
    """Hızlandırılmış görüntü karşılaştırması"""
    try:
        # Görüntüleri yükle
        img1 = cv2.imdecode(np.frombuffer(img1_bytes, np.uint8), cv2.IMREAD_GRAYSCALE)
        img2 = cv2.imdecode(np.frombuffer(img2_bytes, np.uint8), cv2.IMREAD_GRAYSCALE)
        
        if img1 is None or img2 is None:
            return 0
        
        # Küçük boyutta karşılaştır (150x150 yeterli)
        img1 = cv2.resize(img1, (150, 150))
        img2 = cv2.resize(img2, (150, 150))
        
        # Sadece SSIM kullan (en hızlı ve güvenilir)
        ssim_score, _ = ssim(img1, img2, full=False)
        
        return 1 if ssim_score > 0.95 else 0
    except Exception:
        return 0

def process_batch(batch_pairs, svg_contents):
    """Batch halinde işlem yap"""
    results = []
    
    for pair in batch_pairs:
        img1_name, img2_name = pair
        
        # PNG'ye çevir
        png1 = svg_to_png_optimized(svg_contents[img1_name])
        png2 = svg_to_png_optimized(svg_contents[img2_name])
        
        if png1 and png2:
            similarity = compare_images_fast(png1, png2)
            if similarity == 1:
                results.append((img1_name, img2_name))
    
    return results

def find_duplicates_optimized(svg_contents, progress_callback=None):
    """Optimize edilmiş duplikasyon bulma"""
    start_time = time.time()
    
    print(Fore.CYAN + f"Starting duplicate detection for {len(svg_contents)} files..." + Style.RESET_ALL)
    
    # 1. Hızlı hash kontrolü
    exact_duplicates, hash_groups = quick_duplicate_check(svg_contents)
    
    if progress_callback:
        progress_callback({"stage": "hash_check", "duplicates": len(exact_duplicates)})
    
    print(Fore.GREEN + f"Hash check found {len(exact_duplicates)} exact duplicates" + Style.RESET_ALL)
    
    # 2. Hash'i farklı dosyalar için görsel karşılaştırma
    unique_files = []
    for file_group in hash_groups.values():
        unique_files.append(file_group[0])  # Her gruptan bir dosya al
    
    if len(unique_files) <= 1:
        return exact_duplicates, f"Found {len(exact_duplicates)} duplicate pairs using hash comparison."
    
    # 3. Batch'ler halinde işle
    all_pairs = list(itertools.combinations(unique_files, 2))
    visual_duplicates = []
    
    print(Fore.YELLOW + f"Starting visual comparison for {len(all_pairs)} pairs..." + Style.RESET_ALL)
    
    # Timeout kontrolü
    if time.time() - start_time > TIMEOUT_SECONDS:
        return exact_duplicates, "Timeout reached, returning hash-based duplicates only."
    
    # Batch işleme
    batch_count = 0
    total_batches = (len(all_pairs) + BATCH_SIZE - 1) // BATCH_SIZE
    
    for i in range(0, len(all_pairs), BATCH_SIZE):
        if time.time() - start_time > TIMEOUT_SECONDS:
            print(Fore.RED + "Timeout reached during visual comparison" + Style.RESET_ALL)
            break
            
        batch = all_pairs[i:i + BATCH_SIZE]
        batch_results = process_batch(batch, svg_contents)
        visual_duplicates.extend(batch_results)
        
        batch_count += 1
        if progress_callback:
            progress_callback({
                "stage": "visual_comparison", 
                "progress": batch_count / total_batches * 100,
                "duplicates_found": len(visual_duplicates)
            })
        
        print(Fore.BLUE + f"Batch {batch_count}/{total_batches} completed, found {len(batch_results)} duplicates" + Style.RESET_ALL)
    
    # Sonuçları birleştir
    all_duplicates = exact_duplicates + visual_duplicates
    elapsed_time = time.time() - start_time
    
    message = f"Found {len(all_duplicates)} duplicate pairs in {elapsed_time:.2f} seconds."
    print(Fore.GREEN + message + Style.RESET_ALL)
    return all_duplicates, message

def get_image_source_compressed(svg_content):
    """Kompres edilmiş base64 response"""
    try:
        # SVG'yi küçült
        if len(svg_content) > 50000:  # 50KB'dan büyükse
            # Basit bir sıkıştırma
            compressed = gzip.compress(svg_content)
            if len(compressed) < len(svg_content):
                encoded_string = base64.b64encode(compressed).decode('utf-8')
                return f"data:application/gzip;base64,{encoded_string}"
        
        encoded_string = base64.b64encode(svg_content).decode('utf-8')
        return f"data:image/svg+xml;base64,{encoded_string}"
    except Exception:
        return None

# Eski fonksiyonları backward compatibility için tutuyoruz
def svg_to_png(svg_path, png_path):
    """Eski fonksiyon - backward compatibility için"""
    try:
        if os.path.basename(svg_path) == '.DS_Store':
            return False
        if os.path.getsize(svg_path) > 0:
            cairosvg.svg2png(url=svg_path, write_to=png_path)
            return True
        else:
            print(Fore.RED + f"SVG file is empty: {svg_path}" + Style.RESET_ALL)
            return False
    except Exception as e:
        print(Fore.RED + f"Error processing SVG file: {svg_path}, Error: {e}" + Style.RESET_ALL)
        return False

def get_image_source(image_path):
    """Eski fonksiyon - backward compatibility için"""
    with open(image_path, "rb") as image_file:
        encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
    return f"data:image/svg+xml;base64,{encoded_string}"

@app.route('/')
def hello_world():
    return 'Hello, World!'

@app.route('/upload', methods=['POST'])
@cross_origin()
def upload_files():
    if 'file' not in request.files:
        return jsonify({"isSuccess": False, "error": "No file part"}), 400
    
    files = request.files.getlist('file')
    
    # Dosya sayısı kontrolü
    if len(files) > MAX_FILES:
        return jsonify({
            "isSuccess": False, 
            "error": f"Too many files. Maximum {MAX_FILES} files allowed."
        }), 400
    
    # SVG içeriklerini memory'de tut
    svg_contents = {}
    
    for file in files:
        if file.filename == '':
            continue
            
        if file and file.filename.endswith('.svg'):
            content = file.read()
            
            # Dosya boyutu kontrolü
            if len(content) > MAX_FILE_SIZE:
                return jsonify({
                    "isSuccess": False, 
                    "error": f"File {file.filename} is too large. Maximum {MAX_FILE_SIZE/1024/1024}MB allowed."
                }), 400
            
            if len(content.strip()) > 0:
                svg_contents[file.filename] = content

    if not svg_contents:
        return jsonify({"isSuccess": False, "error": "No valid SVG files uploaded"}), 400

    try:
        # Progress tracking için callback
        def progress_callback(data):
            print(f"Progress: {data}")
        
        duplicate_pairs, message = find_duplicates_optimized(svg_contents, progress_callback)
        
        # Response'u optimize et
        data = []
        max_return_count = min(50, len(duplicate_pairs))  # Maksimum 50 duplikat döndür
        
        for pair in duplicate_pairs[:max_return_count]:
            source1 = get_image_source_compressed(svg_contents[pair[0]])
            source2 = get_image_source_compressed(svg_contents[pair[1]])
            
            if source1 and source2:  # Sadece başarılı olanları ekle
                data.append({
                    "fileName": pair[0],
                    "source": source1,
                    "fileName2": pair[1],
                    "source2": source2
                })

        return jsonify({
            "isSuccess": True, 
            "message": message, 
            "data": data,
            "totalDuplicates": len(duplicate_pairs),
            "returnedCount": len(data),
            "performance": {
                "totalFiles": len(svg_contents),
                "maxFilesAllowed": MAX_FILES,
                "timeoutSeconds": TIMEOUT_SECONDS
            }
        }), 200

    except Exception as e:
        print(Fore.RED + f"Error during processing: {str(e)}" + Style.RESET_ALL)
        return jsonify({"isSuccess": False, "error": str(e)}), 500

@app.errorhandler(Exception)
def handle_error(error):
    print(Fore.RED + f"Unhandled error: {str(error)}" + Style.RESET_ALL)
    return jsonify({"isSuccess": False, "error": str(error)}), 500

if __name__ == "__main__":
    print(Fore.GREEN + "Starting optimized SVG duplicate detection server..." + Style.RESET_ALL)
    print(Fore.CYAN + f"Configuration:" + Style.RESET_ALL)
    print(f"  - Max files: {MAX_FILES}")
    print(f"  - Max file size: {MAX_FILE_SIZE/1024/1024}MB")
    print(f"  - Batch size: {BATCH_SIZE}")
    print(f"  - Timeout: {TIMEOUT_SECONDS}s")
    print(f"  - Max workers: {MAX_WORKERS}")
    
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
