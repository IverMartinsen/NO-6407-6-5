# TO-DO_
# - Add argparse
# - split into pure functions
# - fix "RuntimeWarning: divide by zero encountered in log entropy = -np.sum(y_prob * np.log(y_prob), axis=1)

import os
import sys

sys.path.append(os.getcwd())

import glob
import h5py
import json
import time
import torch
import joblib
import numpy as np
import pandas as pd
from PIL import Image
from utils import load_hdf5, read_fn, lab_to_name
from training.utils import LinearClassifier

# args
src_data = 'data/NO 6407-6-5'
alpha = 0.95
#src_models = [ # 10 seeds and 6 classes
#    './training/trained_models/20250210152137_seed1',
#    './training/trained_models/20250210155635_seed2',
#    './training/trained_models/20250210163107_seed3',
#    './training/trained_models/20250210170115_seed4',
#    './training/trained_models/20250210173135_seed5',
#    './training/trained_models/20250210180149_seed6',
#    './training/trained_models/20250210183208_seed7',
#    './training/trained_models/20250210190244_seed8',
#    './training/trained_models/20250210193252_seed9',
#    './training/trained_models/20250210200258_seed10',
#]
src_models = [ # 10 seeds and 20 classes
    "./training/trained_models/20241223150033",
    "./training/trained_models/20241223154957",
    "./training/trained_models/20241223155034",
    "./training/trained_models/20241223160703",
    "./training/trained_models/20241223160725",
    "./training/trained_models/20241223165621",
    "./training/trained_models/20241223165637",
    "./training/trained_models/20241223183148",
    "./training/trained_models/20241223183241",
    "./training/trained_models/20241223204815",
]
#src_models = [
#    '/Users/ima029/Desktop/NO 6407-6-5/training/trained_models/20250103120412',
#]
path_to_ood_detector = './training/ood_detector/ood_detector.pkl'
use_ood_detector = True
#lab_to_name = json.load(open('/Users/ima029/Desktop/NO 6407-6-5/data/BaileyLabels/imagefolder-bisaccate/lab_to_name.json'))
lab_to_name = json.load(open('/Users/ima029/Desktop/NO 6407-6-5/data/labelled imagefolders/imagefolder_20/lab_to_name.json'))
classes = range(len(lab_to_name))
#classes = 4, 7, 17, 18, 21, 23
classes = [4]
# args end

# Make folder for results
timestring = time.strftime("%Y%m%d%H%M%S")
folder = "./4-conformal-prediction/results/" + os.path.basename(src_data) + f"_alpha_{alpha}_{timestring}"

os.makedirs(folder, exist_ok=True)

# copy lab_to_name to folder
with open(os.path.join(folder, "lab_to_name.json"), "w") as f:
    json.dump(lab_to_name, f)

feature_paths = os.path.join(src_data, "features")
feature_paths = glob.glob(feature_paths + "/*.hdf5")
feature_paths.sort()

image_folder = os.path.join(src_data, "hdf5")

ood_detector = joblib.load(path_to_ood_detector)

classifiers = []
entropies = []

for path in src_models:
    classifier = LinearClassifier(384, len(lab_to_name))
    classifier.load_state_dict(torch.load(os.path.join(path, "classifier.pth"), map_location="cpu"))
    classifiers.append(classifier)

    with open(os.path.join(path, "entropy.json")) as f:
        entropies.append(json.load(f))

ref_ent = {}
for k in lab_to_name.values():
    ref_ent[k] = []
    for e in entropies:
        ref_ent[k] += e[k]

with open(os.path.join(folder, "ref_entropy.json"), "w") as f:
    json.dump(ref_ent, f)

detections = []
total_counts = []
entropies_un = []
preds = []

for path_to_features in feature_paths:
    # =============================================================================
    # FEATURE LOADING STEP
    # =============================================================================
    path_to_images = os.path.join(image_folder, os.path.basename(path_to_features).replace("_features", ""))
    f_un, x_un, _ = load_hdf5(path_to_features)
    print(f"Loaded {x_un.shape[0]} features.")

    # check for nan values
    nans = np.unique(np.argwhere(np.isnan(x_un))[:, 0])
    infs = np.unique(np.argwhere(np.isinf(x_un))[:, 0])
    if len(nans) > 0 or len(infs) > 0:
        print(f"Warning! Found {len(nans)} NaN values and {len(infs)} inf values in {os.path.basename(path_to_features)}.")
        idxs = np.unique(np.concatenate([nans, infs]))
        f_un = np.delete(f_un, idxs)
        x_un = np.delete(x_un, idxs, axis=0)
    
    count = x_un.shape[0]
    total_counts.append((os.path.basename(path_to_images), count))
    
    # =============================================================================
    # OOD DETECTION STEP
    # =============================================================================
    if use_ood_detector:
        try:
            pred = ood_detector.predict(x_un)
        except ValueError:
            breakpoint()
            
        _, counts = np.unique(pred, return_counts=True)
        try:
            num_black = counts[1]
        except IndexError:
            num_black = 0
        try:
            num_blurry = counts[2]
        except IndexError:
            num_blurry = 0
        print(f"Detected {num_black} black and {num_blurry} blurry images.")
        print(f"Removing {num_black + num_blurry} images.")
        f_un = f_un[pred == 0]
        x_un = x_un[pred == 0]

    # =============================================================================
    # ENTROPY FILTERING STEP
    # =============================================================================
    logits = []
    for classifier in classifiers:
        logits.append(classifier(torch.tensor(x_un).float()).detach().numpy())
    logits = np.mean(logits, axis=0)
    y_prob = torch.nn.functional.softmax(torch.tensor(logits), dim=-1).numpy()
    
    y_pred = np.argmax(y_prob, axis=1)
    entropy = -np.sum(y_prob * np.log(y_prob), axis=1)
    entropies_un.append(entropy)
    preds.append(y_pred)

    # =============================================================================
    # CLASS-WISE QUANTILE COMPUTATION AND DETECTION STEP
    # =============================================================================
    for k in classes:

        e = ref_ent[lab_to_name[str(k)]]
        q = np.quantile(e, 1 - alpha)
    
        fnames = f_un[(y_pred == k) & (entropy < q)]

        for file in fnames:
            with h5py.File(path_to_images, 'r') as f:
                img = f[file][()]
                img = read_fn(img)
                img = Image.fromarray(img)
                os.makedirs(os.path.join(folder, lab_to_name[str(k)]), exist_ok=True)
                img.save(os.path.join(folder, lab_to_name[str(k)], f"{file}.png"))
        
        detections += (list(zip([os.path.basename(path_to_images)] * len(fnames), fnames, [k] * len(fnames), [lab_to_name[str(k)]] * len(fnames))))

df = pd.DataFrame(detections, columns=["source", "filename", "label", "genus"])
df.to_csv(os.path.join(folder, "stats.csv"), index=False)
# save total counts
df = pd.DataFrame(total_counts, columns=["source", "count"])
df.to_csv(os.path.join(folder, "counts.csv"), index=False)
# save entropies
entropies_un = np.concatenate(entropies_un)
preds = np.concatenate(preds)
d = {}
for i in range(len(lab_to_name)):
    idx = np.where(preds == i)[0]
    d[lab_to_name[str(i)]] = entropies_un[idx].tolist()
with open(os.path.join(folder, "entropy.json"), "w") as f:
    json.dump(d, f)