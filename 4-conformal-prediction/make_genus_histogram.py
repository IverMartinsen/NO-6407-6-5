# TODO: 
# Implement fdr


import os
import argparse
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt


parser = argparse.ArgumentParser()
parser.add_argument("--src", type=str, default=None)
parser.add_argument("--alpha", type=float, default=None)
parser.add_argument("--x_lim", nargs="+", type=int, default=None)
parser.add_argument("--fontsize", type=int, default=18)
args = parser.parse_args()



def load_stats(path_to_stats):
    """
    Load and process the stats file.
    """
    stats = pd.read_csv(path_to_stats)
    
    slides = np.unique(stats["source"].values)

    genus_counts = {}

    for slide in slides:
        df = stats[stats["source"] == slide]
        count = np.unique(df["genus"].values, return_counts=True)
        genus_counts[slide] = dict(zip(count[0], count[1]))

    df = pd.DataFrame(genus_counts).T.fillna(0).astype(int)
    
    return df

def load_counts(path_to_counts):
    """
    Load and process the counts file.
    """
    counts = pd.read_csv(path_to_counts)
    counts.index = counts["source"].values # set index
    counts = counts.drop(columns=["source"])
    return counts

def get_classes(path_to_stats):
    """
    Get the classes from the stats file.
    """
    stats = pd.read_csv(path_to_stats)
    classes = np.unique(stats["genus"].values)
    return classes

def split(x, sep):
    """
    Split a list of strings into a flat list of strings.
    """
    x = [s.split(sep) for s in x]
    # flatten the list

    x = [item for sublist in x for item in sublist]
    return x

def extract_numbers(x, seps):
    """
    Extract all numbers from a string.
    """
    x = [x]
    for sep in seps:
        x = split(x, sep)
    x = [item for item in x if item.isnumeric()]
    x = [int(float(item)) for item in x]
    return x

def infer_depth(x):
    """
    Infer the depth from the string.
    """
    seps = ["_", " ", "-", "."]
    x = extract_numbers(x, seps)
    d = x[np.where(np.array(x) > 1000)[0][0]]
    return d


if __name__ == "__main__":
    src = args.src
    alpha = args.alpha
    fontsize = args.fontsize
    
    stats_df = load_stats(os.path.join(src, "stats.csv"))
    count_df = load_counts(os.path.join(src, "counts.csv"))

    # merge the two dataframes
    df = stats_df.merge(count_df, left_index=True, right_index=True, how="outer") # outer join
    df = df.fillna(0).astype(int)

    # get the classes
    classes = get_classes(os.path.join(src, "stats.csv"))
    fdr = {i: 0 for i in classes} # Not implemented yet

    # infer the depth
    df["depth"] = df.index.map(infer_depth)

    if args.x_lim is None:
        span = (df["depth"].min(), df["depth"].max())
    else:
        span = args.x_lim
    
    df = df.loc[(df["depth"] >= span[0]) & (df["depth"] <= span[1])]

    cmap = plt.get_cmap("tab20")
    iterable = iter(cmap.colors)

    for c in classes:
        
        x = df["depth"]
        y = ((df[c]) * (1 - fdr[c]) / (1 - alpha)).rolling(window=1).mean()
        
        plt.figure(figsize=(20, 10))
        plt.bar(x, y, label="Genus count", width=3)
        plt.xticks(np.arange(span[0], span[1], 20), rotation=45, fontsize=fontsize)
        plt.xlabel("Depth", fontsize=fontsize)
        plt.ylabel("Count", fontsize=fontsize)
        plt.title(f"{c} distribution", fontsize=fontsize)
        plt.tight_layout()
        plt.savefig(os.path.join(src, f"{c}_distribution.png"))
        plt.close()


## joint plot
#tmp = df.copy()
#tmp.index = tmp.depth
#tmp.drop(columns=["depth", "count"], inplace=True)
#for i in tmp.columns:
#    tmp[i] = (tmp[i] * (1 - fdr[i]) / (1 - alpha))
#tmp.columns = [lab_to_name[i] for i in tmp.columns]
#
#tmp.plot(kind="bar", stacked=True, figsize=(20, 10), fontsize=4)
#plt.savefig(f'/Users/ima029/Desktop/NO 6407-6-5/postprocessing/results/NO 6407-6-5_alpha_{alpha}/joint_distribution.png')
#plt.close()