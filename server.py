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

# Initialize colorama
init()

app = Flask(__name__)
UPLOAD_FOLDER = 'uploaded_svgs'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def svg_to_png(svg_path, png_path):
    try:
        if os.path.basename(svg_path) == '.DS_Store':
            return False
        if os.path.getsize(svg_path) > 0:  # Check if the file is not empty
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

    if image1 is None:
        print(Fore.RED + f"Could not read image: {image1_path}" + Style.RESET_ALL)
        return None
    if image2 is None:
        print(Fore.RED + f"Could not read image: {image2_path}" + Style.RESET_ALL)
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

def find_duplicates(folder_path):
    duplicate_pairs = []
    image_files = [f for f in os.listdir(folder_path) if f.endswith('.svg')]
    
    def process_pair(img1_name, img2_name):
        img1_path = os.path.join(folder_path, img1_name)
        img2_path = os.path.join(folder_path, img2_name)

        # SVG dosyalarını kontrol et
        if not os.path.getsize(img1_path) or not os.path.getsize(img2_path):
            print(Fore.YELLOW + f"Empty SVG file: {img1_name} or {img2_name}" + Style.RESET_ALL)
            return None

        with tempfile.NamedTemporaryFile(suffix=".png") as temp1, tempfile.NamedTemporaryFile(suffix=".png") as temp2:
            if not svg_to_png(img1_path, temp1.name) or not svg_to_png(img2_path, temp2.name):
                return None

            similarity_score = compare_images((temp1.name, temp2.name))
            if similarity_score == 1:
                return (img1_name, img2_name)
        return None

    with ThreadPoolExecutor(max_workers=4) as executor:
        # İşlem yürütme
        futures = [executor.submit(lambda pair: process_pair(*pair), (img1, img2)) for img1, img2 in itertools.combinations(image_files, 2)]
        # İşlem tamamlandığında sonuçları al
        results = [future.result() for future in futures]
    
    duplicate_pairs = [result for result in results if result is not None]

    if duplicate_pairs:
        message = "Duplicate images found."
    else:
        message = "No duplicate images found."

    return duplicate_pairs, message

def get_image_source(image_path):
    with open(image_path, "rb") as image_file:
        encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
    return f"data:image/svg+xml;base64,{encoded_string}"

@app.route('/upload', methods=['POST'])
def upload_files():
    if 'file' not in request.files:
        return jsonify({"isSuccess": False, "error": "No file part"}), 400
    
    files = request.files.getlist('file')
    temp_folder = os.path.join(UPLOAD_FOLDER, str(uuid.uuid4()))  # Benzersiz geçici klasör oluştur

    os.makedirs(temp_folder)  # Geçici klasörü oluştur

    for file in files:
        if file.filename == '':
            return jsonify({"isSuccess": False, "error": "No selected file"}), 400
        
        if file and file.filename.endswith('.svg'):
            file.save(os.path.join(temp_folder, file.filename))

    duplicate_pairs, message = find_duplicates(temp_folder)
    
    data = []
    for pair in duplicate_pairs:
        data.append({
            "fileName": pair[0],
            "source": get_image_source(os.path.join(temp_folder, pair[0])),
            "fileName2": pair[1],
            "source2": get_image_source(os.path.join(temp_folder, pair[1]))
        })
    
    # Geçici klasörü temizle
    shutil.rmtree(temp_folder)

    return jsonify({"isSuccess": True, "message": message, "data": data}), 200

@app.errorhandler(Exception)
def handle_error(error):
    return jsonify({"isSuccess": False, "error": str(error)}), 500

if __name__ == "__main__":
    app.run(debug=True)
