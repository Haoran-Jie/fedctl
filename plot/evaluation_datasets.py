#!/usr/bin/env python3
from __future__ import annotations

import gzip
import pickle
import struct
import tarfile
import warnings
from pathlib import Path
from urllib.request import urlretrieve

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np

from common import (
    TMP_DIR,
    apply_publication_style_no_grid,
    save_figure_plot_with_writeup_pdf,
)

CACHE_DIR = TMP_DIR / "evaluation_datasets"
CIFAR_URL = "https://www.cs.toronto.edu/~kriz/cifar-10-python.tar.gz"
FASHION_IMAGES_URL = "http://fashion-mnist.s3-website.eu-central-1.amazonaws.com/train-images-idx3-ubyte.gz"
FASHION_LABELS_URL = "http://fashion-mnist.s3-website.eu-central-1.amazonaws.com/train-labels-idx1-ubyte.gz"
CALIFORNIA_URL = "https://storage.googleapis.com/tensorflow/tf-keras-datasets/california_housing.npz"

CIFAR_CLASSES = [
    "airplane",
    "auto",
    "bird",
    "cat",
    "deer",
    "dog",
    "frog",
    "horse",
    "ship",
    "truck",
]
FASHION_CLASSES = [
    "T-shirt",
    "trouser",
    "pullover",
    "dress",
    "coat",
    "sandal",
    "shirt",
    "sneaker",
    "bag",
    "boot",
]


def _cached_download(url: str, filename: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / filename
    if not path.exists():
        print(f"Downloading {url}", flush=True)
        urlretrieve(url, path)
    return path


def _load_cifar_samples() -> tuple[list[np.ndarray], list[int]]:
    archive = _cached_download(CIFAR_URL, "cifar-10-python.tar.gz")
    with tarfile.open(archive, "r:gz") as tar:
        member = tar.extractfile("cifar-10-batches-py/data_batch_1")
        if member is None:
            raise RuntimeError("CIFAR-10 archive missing data_batch_1")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            payload = pickle.load(member, encoding="latin1")
    data = np.asarray(payload["data"], dtype=np.uint8).reshape(-1, 3, 32, 32)
    images = np.transpose(data, (0, 2, 3, 1))
    labels = [int(label) for label in payload["labels"]]
    return _one_per_class(images, labels, seed=2026)


def _load_fashion_samples() -> tuple[list[np.ndarray], list[int]]:
    image_path = _cached_download(FASHION_IMAGES_URL, "fashion-train-images-idx3-ubyte.gz")
    label_path = _cached_download(FASHION_LABELS_URL, "fashion-train-labels-idx1-ubyte.gz")
    with gzip.open(image_path, "rb") as f:
        magic, count, rows, cols = struct.unpack(">IIII", f.read(16))
        if magic != 2051:
            raise RuntimeError(f"Unexpected Fashion-MNIST image magic: {magic}")
        images = np.frombuffer(f.read(), dtype=np.uint8).reshape(count, rows, cols)
    with gzip.open(label_path, "rb") as f:
        magic, count = struct.unpack(">II", f.read(8))
        if magic != 2049:
            raise RuntimeError(f"Unexpected Fashion-MNIST label magic: {magic}")
        labels = [int(label) for label in np.frombuffer(f.read(), dtype=np.uint8)]
    return _one_per_class(images, labels, seed=2027)


def _load_california_arrays() -> tuple[np.ndarray, np.ndarray]:
    npz_path = _cached_download(CALIFORNIA_URL, "california_housing.npz")
    with np.load(npz_path) as raw:
        x = np.asarray(raw["x"], dtype=np.float64)
        y = np.asarray(raw["y"], dtype=np.float64)
    # TensorFlow's cached California Housing array follows the original order:
    # longitude, latitude, age, rooms, bedrooms, population, households, income.
    return x[:, 7], y


def _one_per_class(images: np.ndarray, labels: list[int], *, seed: int) -> tuple[list[np.ndarray], list[int]]:
    rng = np.random.default_rng(seed)
    by_label: dict[int, list[int]] = {}
    for idx, label in enumerate(labels):
        by_label.setdefault(label, []).append(idx)
    chosen_images: list[np.ndarray] = []
    chosen_labels: list[int] = []
    for label in range(10):
        idx = int(rng.choice(by_label[label]))
        chosen_images.append(images[idx])
        chosen_labels.append(label)
    return chosen_images, chosen_labels


def _image_grid_figure(
    images: list[np.ndarray],
    labels: list[int],
    class_names: list[str],
    *,
    grayscale: bool,
    stem: str,
) -> None:
    fig, axes = plt.subplots(2, 5, figsize=(9.5, 3.2))
    for ax, image, label in zip(axes.ravel(), images, labels, strict=True):
        ax.imshow(image, cmap="gray" if grayscale else None, interpolation="nearest")
        ax.set_xticks([])
        ax.set_yticks([])
        ax.set_title(class_names[label], fontsize=11, pad=3)
        for spine in ax.spines.values():
            spine.set_color("0.78")
            spine.set_linewidth(0.6)
    fig.tight_layout(w_pad=0.25, h_pad=0.55)
    outputs = save_figure_plot_with_writeup_pdf(fig, stem)
    plt.close(fig)
    print(f"Wrote {outputs['pdf'][0]}")
    print(f"Wrote {outputs['pdf'][1]}")


def _california_scatter_figure(med_inc: np.ndarray, house_val: np.ndarray) -> None:
    sample = np.random.default_rng(2028).choice(
        np.arange(med_inc.shape[0]),
        size=min(3500, med_inc.shape[0]),
        replace=False,
    )
    fig, ax = plt.subplots(figsize=(6.2, 3.45))
    ax.scatter(
        med_inc[sample],
        house_val[sample],
        s=7,
        color="#2A6F62",
        alpha=0.25,
        linewidths=0,
    )
    ax.set_xlabel("Median income")
    ax.set_ylabel("Median house value")
    ax.grid(True, color="0.82", linewidth=0.45)
    ax.set_xlim(left=0)
    ax.set_ylim(bottom=0)
    fig.tight_layout()
    outputs = save_figure_plot_with_writeup_pdf(fig, "evaluation_task_california_housing_scatter")
    plt.close(fig)
    print(f"Wrote {outputs['pdf'][0]}")
    print(f"Wrote {outputs['pdf'][1]}")


def main() -> None:
    apply_publication_style_no_grid()
    plt.rcParams.update(
        {
            "axes.titlesize": 16,
            "axes.labelsize": 14,
            "xtick.labelsize": 11,
            "ytick.labelsize": 11,
        }
    )

    cifar_images, cifar_labels = _load_cifar_samples()
    fashion_images, fashion_labels = _load_fashion_samples()
    med_inc, house_val = _load_california_arrays()
    _image_grid_figure(
        cifar_images,
        cifar_labels,
        CIFAR_CLASSES,
        grayscale=False,
        stem="evaluation_task_cifar10_samples",
    )
    _image_grid_figure(
        fashion_images,
        fashion_labels,
        FASHION_CLASSES,
        grayscale=True,
        stem="evaluation_task_fashion_mnist_samples",
    )
    _california_scatter_figure(med_inc, house_val)


if __name__ == "__main__":
    main()
