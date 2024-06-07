import cairosvg
import os
import cv2
from skimage.metrics import structural_similarity as ssim
from concurrent.futures import ThreadPoolExecutor
import itertools
import tempfile
from tabulate import tabulate
from colorama import init, Fore, Style

# Initialize colorama
init()

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

    score, _ = ssim(gray1, gray2, full=True)
    return score

def find_duplicates(folder_path):
    duplicate_pairs = []
    image_files = [f for f in os.listdir(folder_path) if f.endswith('.svg')]
    
    def process_pair(img1_name, img2_name):
        img1_path = os.path.join(folder_path, img1_name)
        img2_path = os.path.join(folder_path, img2_name)

        with tempfile.NamedTemporaryFile(suffix=".png") as temp1, tempfile.NamedTemporaryFile(suffix=".png") as temp2:
            if not svg_to_png(img1_path, temp1.name) or not svg_to_png(img2_path, temp2.name):
                return None

            similarity_score = compare_images((temp1.name, temp2.name))
            if similarity_score is not None and similarity_score == 1:
                return (img1_path, img2_path)
        return None

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda pair: process_pair(*pair), itertools.combinations(image_files, 2)))
    
    duplicate_pairs = [result for result in results if result is not None]
    return duplicate_pairs

def print_duplicates(duplicate_pairs):
    if duplicate_pairs:
        table = [[os.path.basename(pair[0]), os.path.basename(pair[1])] for pair in duplicate_pairs]
        print(Fore.GREEN + "Duplicate image pairs found:" + Style.RESET_ALL)
        print(tabulate(table, headers=["Image 1", "Image 2"], tablefmt="grid"))
    else:
        print(Fore.YELLOW + "No duplicate image pairs found." + Style.RESET_ALL)

if __name__ == "__main__":
    folder_path = os.path.join(os.getcwd(), 'icons')
    duplicate_pairs = find_duplicates(folder_path)
    print_duplicates(duplicate_pairs)
    
    if duplicate_pairs:
        with open('duplicate_log.txt', 'w') as f:
            f.write("Duplicate image pairs:\n")
            for pair in duplicate_pairs:
                f.write(f"These files are identical: {' '.join(pair)}\n")
        print(Fore.GREEN + "Duplicate image pairs logged in duplicate_log.txt" + Style.RESET_ALL)
    else:
        print(Fore.YELLOW + "No duplicate image pairs found." + Style.RESET_ALL)
