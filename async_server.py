from flask import Flask, request, jsonify
import os
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor
import itertools
import base64
import cairosvg
import cv2
from skimage.metrics import structural_similarity as ssim
from colorama import init, Fore, Style
import uuid
import numpy as np
from flask_cors import cross_origin, CORS
import threading
import time
from datetime import datetime, timedelta
import json

# Initialize colorama
init()

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

UPLOAD_FOLDER = 'uploaded_svgs'
JOBS_FOLDER = 'jobs'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(JOBS_FOLDER, exist_ok=True)

# In-memory job storage (in production, use Redis or database)
jobs = {}
job_lock = threading.Lock()

class JobStatus:
    PENDING = 'pending'
    PROCESSING = 'processing'
    COMPLETED = 'completed'
    FAILED = 'failed'

def svg_to_png(svg_path, png_path):
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

def compare_images(image_pair):
    image1_path, image2_path = image_pair
    image1 = cv2.imread(image1_path)
    image2 = cv2.imread(image2_path)

    if image1 is None or image2 is None:
        return None

    image1 = cv2.resize(image1, (300, 300))
    image2 = cv2.resize(image2, (300, 300))

    gray1 = cv2.cvtColor(image1, cv2.COLOR_BGR2GRAY)
    gray2 = cv2.cvtColor(image2, cv2.COLOR_BGR2GRAY)

    # SSIM score
    ssim_score, _ = ssim(gray1, gray2, full=True)
    
    # MSE score
    mse_score = np.mean((gray1 - gray2) ** 2)
    
    # Histogram comparison
    hist1 = cv2.calcHist([gray1], [0], None, [256], [0, 256])
    hist2 = cv2.calcHist([gray2], [0], None, [256], [0, 256])
    hist_score = cv2.compareHist(hist1, hist2, cv2.HISTCMP_CORREL)
    
    # Combining scores with thresholding
    if ssim_score > 0.95 and mse_score < 100 and hist_score > 0.9:
        return 1
    return 0

def update_job_progress(job_id, processed, total):
    with job_lock:
        if job_id in jobs:
            jobs[job_id]['progress'] = {
                'processed': processed,
                'total': total,
                'percentage': round((processed / total) * 100, 2) if total > 0 else 0
            }

def find_duplicates_async(job_id, folder_path):
    try:
        with job_lock:
            jobs[job_id]['status'] = JobStatus.PROCESSING
            jobs[job_id]['started_at'] = datetime.now().isoformat()
        
        duplicate_pairs = []
        image_files = [f for f in os.listdir(folder_path) if f.endswith('.svg')]
        total_pairs = len(list(itertools.combinations(image_files, 2)))
        processed_pairs = 0
        
        def process_pair(img1_name, img2_name):
            nonlocal processed_pairs
            img1_path = os.path.join(folder_path, img1_name)
            img2_path = os.path.join(folder_path, img2_name)

            if not os.path.getsize(img1_path) or not os.path.getsize(img2_path):
                processed_pairs += 1
                update_job_progress(job_id, processed_pairs, total_pairs)
                return None

            with tempfile.NamedTemporaryFile(suffix=".png") as temp1, tempfile.NamedTemporaryFile(suffix=".png") as temp2:
                if not svg_to_png(img1_path, temp1.name) or not svg_to_png(img2_path, temp2.name):
                    processed_pairs += 1
                    update_job_progress(job_id, processed_pairs, total_pairs)
                    return None

                similarity_score = compare_images((temp1.name, temp2.name))
                processed_pairs += 1
                update_job_progress(job_id, processed_pairs, total_pairs)
                
                if similarity_score == 1:
                    return (img1_name, img2_name)
            return None

        # Process in smaller batches to allow progress updates
        batch_size = 10
        pairs = list(itertools.combinations(image_files, 2))
        
        with ThreadPoolExecutor(max_workers=4) as executor:
            for i in range(0, len(pairs), batch_size):
                batch = pairs[i:i + batch_size]
                futures = [executor.submit(lambda pair: process_pair(*pair), pair) for pair in batch]
                batch_results = [future.result() for future in futures]
                duplicate_pairs.extend([result for result in batch_results if result is not None])
        
        # Prepare result data
        data = []
        for pair in duplicate_pairs:
            with open(os.path.join(folder_path, pair[0]), "rb") as f1:
                source1 = base64.b64encode(f1.read()).decode('utf-8')
            with open(os.path.join(folder_path, pair[1]), "rb") as f2:
                source2 = base64.b64encode(f2.read()).decode('utf-8')
            
            data.append({
                "fileName": pair[0],
                "source": f"data:image/svg+xml;base64,{source1}",
                "fileName2": pair[1],
                "source2": f"data:image/svg+xml;base64,{source2}"
            })
        
        message = "Duplicate images found." if duplicate_pairs else "No duplicate images found."
        
        with job_lock:
            jobs[job_id]['status'] = JobStatus.COMPLETED
            jobs[job_id]['completed_at'] = datetime.now().isoformat()
            jobs[job_id]['result'] = {
                "message": message,
                "data": data,
                "total_files": len(image_files),
                "duplicates_found": len(duplicate_pairs)
            }
        
        # Clean up temporary folder
        shutil.rmtree(folder_path)
        
    except Exception as e:
        with job_lock:
            jobs[job_id]['status'] = JobStatus.FAILED
            jobs[job_id]['error'] = str(e)
            jobs[job_id]['completed_at'] = datetime.now().isoformat()
        
        # Clean up on error
        if os.path.exists(folder_path):
            shutil.rmtree(folder_path)

@app.route('/')
def hello_world():
    return jsonify({"message": "SVG Duplicate Finder API", "status": "running"})

@app.route('/upload', methods=['POST'])
@cross_origin()
def upload_files():
    if 'file' not in request.files:
        return jsonify({"isSuccess": False, "error": "No file part"}), 400
    
    files = request.files.getlist('file')
    if not files or all(f.filename == '' for f in files):
        return jsonify({"isSuccess": False, "error": "No files selected"}), 400
    
    # Create unique job ID and temp folder
    job_id = str(uuid.uuid4())
    temp_folder = os.path.join(UPLOAD_FOLDER, job_id)
    os.makedirs(temp_folder)
    
    # Save uploaded files
    valid_files = 0
    for file in files:
        if file and file.filename.endswith('.svg'):
            file.save(os.path.join(temp_folder, file.filename))
            valid_files += 1
    
    if valid_files == 0:
        shutil.rmtree(temp_folder)
        return jsonify({"isSuccess": False, "error": "No valid SVG files uploaded"}), 400
    
    # Initialize job
    with job_lock:
        jobs[job_id] = {
            'id': job_id,
            'status': JobStatus.PENDING,
            'created_at': datetime.now().isoformat(),
            'progress': {'processed': 0, 'total': 0, 'percentage': 0},
            'files_count': valid_files
        }
    
    # Start background processing
    thread = threading.Thread(target=find_duplicates_async, args=(job_id, temp_folder))
    thread.daemon = True
    thread.start()
    
    return jsonify({
        "isSuccess": True, 
        "jobId": job_id,
        "message": f"Processing started for {valid_files} files. Use /status/{job_id} to check progress."
    }), 202

@app.route('/status/<job_id>', methods=['GET'])
@cross_origin()
def get_job_status(job_id):
    with job_lock:
        if job_id not in jobs:
            return jsonify({"isSuccess": False, "error": "Job not found"}), 404
        
        job = jobs[job_id].copy()
    
    return jsonify({"isSuccess": True, "job": job})

@app.route('/result/<job_id>', methods=['GET'])
@cross_origin()
def get_job_result(job_id):
    with job_lock:
        if job_id not in jobs:
            return jsonify({"isSuccess": False, "error": "Job not found"}), 404
        
        job = jobs[job_id].copy()
    
    if job['status'] != JobStatus.COMPLETED:
        return jsonify({
            "isSuccess": False, 
            "error": "Job not completed yet",
            "status": job['status']
        }), 400
    
    return jsonify({
        "isSuccess": True,
        "message": job['result']['message'],
        "data": job['result']['data']
    })

# Cleanup old jobs (run periodically)
def cleanup_old_jobs():
    while True:
        try:
            cutoff_time = datetime.now() - timedelta(hours=1)  # Remove jobs older than 1 hour
            with job_lock:
                jobs_to_remove = []
                for job_id, job in jobs.items():
                    created_at = datetime.fromisoformat(job['created_at'])
                    if created_at < cutoff_time:
                        jobs_to_remove.append(job_id)
                
                for job_id in jobs_to_remove:
                    del jobs[job_id]
            
            time.sleep(300)  # Check every 5 minutes
        except Exception as e:
            print(f"Error in cleanup: {e}")
            time.sleep(300)

# Start cleanup thread
cleanup_thread = threading.Thread(target=cleanup_old_jobs)
cleanup_thread.daemon = True
cleanup_thread.start()

@app.errorhandler(Exception)
def handle_error(error):
    return jsonify({"isSuccess": False, "error": str(error)}), 500

if __name__ == "__main__":
    # Railway dynamic port support
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False) 