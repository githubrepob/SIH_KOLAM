# app.py
import os, uuid, random, threading, math, hashlib, time
from flask import Flask, jsonify, request, send_from_directory, abort
import cv2
import numpy as np
from skimage.morphology import skeletonize
import networkx as nx

# Config
IMAGE_FOLDER = os.path.join('static', 'kolam_images')
MAX_TRIES = 3

app = Flask(__name__, static_folder='static', static_url_path='/static')

# In-memory store
captcha_store = {}
lock = threading.Lock()

# ----------------- Utilities: image analysis -----------------
def load_image(path):
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    return img

def count_active_dots(img):
    # Detect blobs / dots using SimpleBlobDetector on thresholded image
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5,5), 0)
    th = cv2.adaptiveThreshold(blur, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                               cv2.THRESH_BINARY_INV, 11, 2)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3,3))
    th = cv2.morphologyEx(th, cv2.MORPH_OPEN, kernel, iterations=1)

    params = cv2.SimpleBlobDetector_Params()
    params.filterByArea = True
    params.minArea = 8
    params.maxArea = 5000
    params.filterByCircularity = False
    params.filterByInertia = False
    params.filterByConvexity = False
    try:
        detector = cv2.SimpleBlobDetector_create(params)
    except:
        detector = cv2.SimpleBlobDetector(params)
    kps = detector.detect(th)
    return len(kps)

def count_squares(img):
    # Detect contours that approximate to quadrilaterals.
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5,5), 0)
    _, th = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    # find contours
    contours, _ = cv2.findContours(255 - th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    quads = 0
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < 100: continue
        peri = cv2.arcLength(cnt, True)
        approx = cv2.approxPolyDP(cnt, 0.04 * peri, True)
        if len(approx) == 4:
            # filter by squareness: check bounding box ratio
            x,y,w,h = cv2.boundingRect(approx)
            ratio = float(w)/h if h>0 else 0
            if 0.6 <= ratio <= 1.6:
                quads += 1
    return quads

def count_loops(img):
    # Skeletonize and compute cycles using graph approach
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, th = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    # We want lines as white
    th = 255 - th
    # skeletonize using skimage expects boolean
    sk = skeletonize(th > 0).astype(np.uint8)
    h,w = sk.shape
    # Build graph where nodes are junctions and endpoints
    G = nx.Graph()
    idx = lambda r,c: r*w + c
    for r in range(h):
        for c in range(w):
            if sk[r,c]:
                # neighbor count
                neigh = 0
                neighbors = []
                for dr in (-1,0,1):
                    for dc in (-1,0,1):
                        if dr==0 and dc==0: continue
                        rr,cc = r+dr, c+dc
                        if 0 <= rr < h and 0 <= cc < w and sk[rr,cc]:
                            neigh += 1
                            neighbors.append((rr,cc))
                if neigh != 2:
                    G.add_node(idx(r,c), pos=(r,c))
                    for (rr,cc) in neighbors:
                        if sk[rr,cc]:
                            G.add_node(idx(rr,cc), pos=(rr,cc))
                            G.add_edge(idx(r,c), idx(rr,cc))
    try:
        cycles = nx.cycle_basis(G)
        return len(cycles)
    except Exception:
        # fallback: try Euler formula estimate using edges/nodes
        E = G.number_of_edges()
        V = G.number_of_nodes()
        C = max(0, E - V + 1)
        return int(C)

def analyze_image(path):
    img = load_image(path)
    if img is None:
        return None
    dots = count_active_dots(img)
    squares = count_squares(img)
    loops = count_loops(img)
    return {'dots': int(dots), 'squares': int(squares), 'loops': int(loops)}

# ----------------- Captcha endpoints -----------------
@app.route('/captcha/new')
def captcha_new():
    # select random image
    files = [f for f in os.listdir(IMAGE_FOLDER) if f.lower().endswith(('.png','.jpg','.jpeg','.webp','.bmp'))]
    if not files:
        return jsonify({'error':'no images found'}), 500
    chosen = random.choice(files)
    path = os.path.join(IMAGE_FOLDER, chosen)
    meta = analyze_image(path)
    # pick a challenge type randomly
    challenge = random.choice(['dots','loops','squares'])
    # form challenge text and canonical numeric answer
    if challenge == 'dots':
        text = 'Count the active dots in the Kolam'
        answer = meta['dots']
    elif challenge == 'loops':
        text = 'Count the loops in the Kolam'
        answer = meta['loops']
    else:
        text = 'Count the squares in the Kolam'
        answer = meta['squares']

    token = str(uuid.uuid4())
    with lock:
        captcha_store[token] = {
            'image': chosen,
            'meta': meta,
            'challenge': challenge,
            'answer': int(answer),
            'tries_left': MAX_TRIES,
            'validated': False,
            'created': time.time()
        }
    # return relative image_url (frontend will prefix if needed)
    return jsonify({'token': token, 'image_url': f'/static/kolam_images/{chosen}', 'challenge_text': text, 'meta': meta})

@app.route('/captcha/verify', methods=['POST'])
def captcha_verify():
    data = request.get_json() or {}
    token = data.get('token')
    answer_raw = str(data.get('answer','')).strip().lower()
    if not token or token not in captcha_store:
        return jsonify({'success': False, 'hint': 'Invalid or expired captcha. Refresh to get a new one.', 'refresh': True}), 400
    with lock:
        entry = captcha_store[token]
        if entry['validated']:
            return jsonify({'success': True, 'msg': 'Already validated'})

        if entry['tries_left'] <= 0:
            return jsonify({'success': False, 'msg': 'No tries left. Refresh captcha.', 'refresh': True, 'tries_left': 0})

    # normalize numeric answer: extract integer
    import re
    m = re.search(r'(-?\d+)', answer_raw)
    if not m:
        with lock:
            entry['tries_left'] = max(0, entry['tries_left'] - 1)
        return jsonify({'success': False, 'hint': 'Could not understand your answer — enter a number like 7.', 'tries_left': entry['tries_left']})

    user_n = int(m.group(1))
    correct = entry['answer']
    with lock:
        if user_n == correct:
            entry['validated'] = True
            return jsonify({'success': True, 'msg': 'Captcha correct!'})
        else:
            entry['tries_left'] = max(0, entry['tries_left'] - 1)
            # engaging hints tailored to challenge
            hint = make_hint(entry['challenge'], user_n, correct, entry['meta'])
            refresh = entry['tries_left'] == 0
            return jsonify({'success': False, 'hint': hint, 'tries_left': entry['tries_left'], 'refresh': refresh})

@app.route('/captcha/hint', methods=['POST'])
def captcha_hint():
    data = request.get_json() or {}
    token = data.get('token')
    if not token or token not in captcha_store:
        return jsonify({'hint': 'Invalid token.'}), 400
    entry = captcha_store[token]
    # gentle progressive hint
    ch = entry['challenge']
    meta = entry['meta']
    if ch == 'dots':
        hint = f"It's not huge — roughly between {max(1, meta['dots']-2)} and {meta['dots']+2}. Look at small circular marks."
    elif ch == 'loops':
        hint = f"Focus on closed strokes. There are about {meta['loops']} closed loops (I won't give exact — try counting distinct cycles)."
    else:
        hint = f"Look for square-like enclosures; some may be nested. Approx: {meta['squares']} (hint: try looking at the center region)."
    return jsonify({'hint': hint})

# ---------- helper ----------

def make_hint(challenge, user_n, correct_n, meta):
    # creative, engaging hint text
    if challenge == 'dots':
        if user_n < correct_n:
            return f"Close — there are more dots than {user_n}. Try scanning rows from left to right."
        else:
            return f"A bit too many — there are fewer than {user_n}. Maybe some small dots are easy to miss."
    elif challenge == 'loops':
        if user_n < correct_n:
            return f"You're under — look for enclosed strokes (tiny loops count too). There are more than {user_n}."
        else:
            return f"You're over — look carefully for where a stroke crosses itself; not every crossing makes a loop."
    else:
        # squares
        if user_n < correct_n:
            return f"There are more square-ish enclosures than {user_n}. Look in the inner grid."
        else:
            return f"You counted too many — some shapes look like squares but are open. Try tracing boundaries."

# debug endpoint (development only)
@app.route('/_debug/captchas')
def debug_captchas():
    with lock:
        return jsonify({k:{'image':v['image'],'challenge':v['challenge'],'answer':v['answer'],'tries_left':v['tries_left']} for k,v in captcha_store.items()})

if __name__ == '__main__':
    if not os.path.isdir(IMAGE_FOLDER):
        os.makedirs(IMAGE_FOLDER, exist_ok=True)
        print("Put some kolam images in", IMAGE_FOLDER)
    app.run(debug=True, port=5000)
