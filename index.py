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
import io
import numpy as np

# Initialize colorama
init()

app = Flask(__name__)
UPLOAD_FOLDER = 'uploaded_svgs'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def svg_to_png(svg_content):
    try:
        png_output = io.BytesIO()
        cairosvg.svg2png(bytestring=svg_content, write_to=png_output)
        png_output.seek(0)
        return png_output
    except Exception as e:
        print(Fore.RED + f"Error processing SVG content: {e}" + Style.RESET_ALL)
        return None

def compare_images(image_pair):
    image1_bytes, image2_bytes = image_pair

    image1 = cv2.imdecode(np.frombuffer(image1_bytes.read(), np.uint8), cv2.IMREAD_UNCHANGED)
    image2 = cv2.imdecode(np.frombuffer(image2_bytes.read(), np.uint8), cv2.IMREAD_UNCHANGED)

    if image1 is None:
        print(Fore.RED + f"Could not read image from bytes" + Style.RESET_ALL)
        return None
    if image2 is None:
        print(Fore.RED + f"Could not read image from bytes" + Style.RESET_ALL)
        return None

    image1 = cv2.resize(image1, (300, 300))
    image2 = cv2.resize(image2, (300, 300))

    gray1 = cv2.cvtColor(image1, cv2.COLOR_BGR2GRAY)
    gray2 = cv2.cvtColor(image2, cv2.COLOR_BGR2GRAY)

    score, _ = ssim(gray1, gray2, full=True)
    return score

def process_pair(pair, svg_contents):
    img1_name, img2_name = pair
    svg_content1 = svg_contents[img1_name]
    svg_content2 = svg_contents[img2_name]

    png1 = svg_to_png(svg_content1)
    png2 = svg_to_png(svg_content2)

    if png1 is None or png2 is None:
        return None

    similarity_score = compare_images((png1, png2))
    if similarity_score is not None and similarity_score == 1:
        return (img1_name, img2_name)
    return None

def find_duplicates(svg_files, svg_contents):
    duplicate_pairs = []

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(process_pair, pair, svg_contents) for pair in itertools.combinations(svg_files, 2)]
        results = [future.result() for future in futures]

    duplicate_pairs = [result for result in results if result is not None]

    if duplicate_pairs:
        message = "Duplicate images found."
    else:
        message = "No duplicate images found."

    return duplicate_pairs, message

def get_image_source(svg_content):
    encoded_string = base64.b64encode(svg_content).decode('utf-8')
    return f"data:image/svg+xml;base64,{encoded_string}"

@app.route('/upload', methods=['POST'])
def upload_files():
    if 'file' not in request.files:
        return jsonify({"isSuccess": False, "error": "No file part"}), 400

    files = request.files.getlist('file')
    temp_folder = os.path.join(UPLOAD_FOLDER, str(uuid.uuid4()))  # Benzersiz geçici klasör oluştur

    os.makedirs(temp_folder)  # Geçici klasörü oluştur

    svg_files = []
    svg_contents = {}

    for file in files:
        if file.filename == '':
            return jsonify({"isSuccess": False, "error": "No selected file"}), 400

        if file and file.filename.endswith('.svg'):
            file_content = file.read()
            if len(file_content.strip()) == 0:
                print(Fore.YELLOW + f"Empty SVG file: {file.filename}" + Style.RESET_ALL)
                continue
            svg_files.append(file.filename)
            svg_contents[file.filename] = file_content

    if not svg_files:
        return jsonify({"isSuccess": False, "error": "No valid SVG files uploaded"}), 400

    try:
        duplicate_pairs, message = find_duplicates(svg_files, svg_contents)
    except Exception as e:
        return jsonify({"isSuccess": False, "error": str(e)}), 500

    data = []
    for pair in duplicate_pairs:
        data.append({
            "fileName": pair[0],
            "source": get_image_source(svg_contents[pair[0]]),
            "fileName2": pair[1],
            "source2": get_image_source(svg_contents[pair[1]])
        })

    # Geçici klasörü temizle
    shutil.rmtree(temp_folder)

    return jsonify({"isSuccess": True, "message": message, "data": data}), 200

@app.errorhandler(Exception)
def handle_error(error):
    return jsonify({"isSuccess": False, "error": str(error)}), 500

if __name__ == "__main__":
    app.run(debug=True)
