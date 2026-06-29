"""Copy-move localization using ORB keypoint self-matching."""

from __future__ import annotations

from collections import Counter
from itertools import combinations

import cv2
import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import connected_components

from pipeline1.pixel_forensics.block_grid import BLOCK_SIZE
from pipeline1.schema import CopyMoveMatch

MIN_SPATIAL_DISTANCE = 3 * BLOCK_SIZE
CLUSTER_DISTANCE = 3 * BLOCK_SIZE
MIN_PAIR_MATCHES = 4
BBOX_PADDING_ORIGINAL = 10


def find_copy_move(
    image_working_res: np.ndarray,
    scale_to_original: float,
) -> list[CopyMoveMatch]:
    """Find copy-move candidates from repeated ORB keypoint neighborhoods."""

    try:
        if image_working_res is None or image_working_res.size == 0:
            return []
        grayscale = cv2.cvtColor(image_working_res, cv2.COLOR_BGR2GRAY)
        keypoints, descriptors = cv2.ORB_create(nfeatures=2000).detectAndCompute(grayscale, None)
        if descriptors is None or len(keypoints) < MIN_PAIR_MATCHES * 2:
            return []

        crosscheck_matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
        raw_crosscheck_matches = crosscheck_matcher.match(descriptors, descriptors)
        matches = _nontrivial_dmatches(raw_crosscheck_matches, keypoints)
        if len(matches) < MIN_PAIR_MATCHES:
            matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
            raw_matches = matcher.knnMatch(descriptors, descriptors, k=8)
            matches = _nontrivial_knn_matches(raw_matches, keypoints)
        if len(matches) < MIN_PAIR_MATCHES:
            return []

        source_labels = _cluster_points([match[0] for match in matches])
        target_labels = _cluster_points([match[1] for match in matches])
        pair_counts = Counter()
        for index in range(len(matches)):
            source_label = source_labels[index]
            target_label = target_labels[index]
            if source_label >= 0 and target_label >= 0:
                pair_counts[(source_label, target_label)] += 1

        results = []
        source_labels_seen = sorted({source_label for source_label, _ in pair_counts})
        for source_label in source_labels_seen:
            target_counts = {
                target_label: count
                for (candidate_source_label, target_label), count in pair_counts.items()
                if candidate_source_label == source_label
            }
            if not target_counts:
                continue
            target_label, match_count = max(target_counts.items(), key=lambda item: item[1])
            if match_count < MIN_PAIR_MATCHES:
                continue
            match_indices = [
                index
                for index in range(len(matches))
                if source_labels[index] == source_label and target_labels[index] == target_label
            ]
            source_points = [
                matches[index][0]
                for index in match_indices
            ]
            target_points = [
                matches[index][1]
                for index in match_indices
            ]
            if len(source_points) < MIN_PAIR_MATCHES or len(target_points) < MIN_PAIR_MATCHES:
                continue
            distances = [matches[index][2].distance for index in match_indices]
            similarity = _similarity_from_distances(distances)
            results.append(
                CopyMoveMatch(
                    source_bbox=_points_bbox_original(
                        source_points,
                        scale_to_original,
                        image_working_res.shape[:2],
                    ),
                    target_bbox=_points_bbox_original(
                        target_points,
                        scale_to_original,
                        image_working_res.shape[:2],
                    ),
                    similarity=similarity,
                )
            )
        return results
    except Exception:
        return []


def _nontrivial_dmatches(
    raw_matches: tuple[cv2.DMatch, ...],
    keypoints: tuple[cv2.KeyPoint, ...],
) -> list[tuple[tuple[float, float], tuple[float, float], cv2.DMatch]]:
    matches = []
    seen_pairs = set()
    for match in raw_matches:
        if match.queryIdx == match.trainIdx:
            continue
        source_point = keypoints[match.queryIdx].pt
        target_point = keypoints[match.trainIdx].pt
        if np.hypot(source_point[0] - target_point[0], source_point[1] - target_point[1]) < MIN_SPATIAL_DISTANCE:
            continue
        pair = tuple(sorted((match.queryIdx, match.trainIdx)))
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        matches.append((source_point, target_point, match))
    return matches


def _nontrivial_knn_matches(
    raw_matches: list[list[cv2.DMatch]],
    keypoints: tuple[cv2.KeyPoint, ...],
) -> list[tuple[tuple[float, float], tuple[float, float], cv2.DMatch]]:
    matches = []
    seen_pairs = set()
    for candidates in raw_matches:
        for match in candidates:
            if match.queryIdx == match.trainIdx:
                continue
            source_point = keypoints[match.queryIdx].pt
            target_point = keypoints[match.trainIdx].pt
            if np.hypot(source_point[0] - target_point[0], source_point[1] - target_point[1]) < MIN_SPATIAL_DISTANCE:
                continue
            pair = tuple(sorted((match.queryIdx, match.trainIdx)))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            matches.append((source_point, target_point, match))
            break
    return matches


def _cluster_points(points: list[tuple[float, float]]) -> np.ndarray:
    if not points:
        return np.asarray([], dtype=int)
    coordinates = np.asarray(points, dtype=float)
    rows = []
    cols = []
    for left, right in combinations(range(len(points)), 2):
        if np.linalg.norm(coordinates[left] - coordinates[right]) <= CLUSTER_DISTANCE:
            rows.extend([left, right])
            cols.extend([right, left])
    data = np.ones(len(rows), dtype=bool)
    graph = csr_matrix((data, (rows, cols)), shape=(len(points), len(points)))
    _, labels = connected_components(graph, directed=False)
    return labels


def _points_bbox_original(
    points: list[tuple[float, float]],
    scale_to_original: float,
    working_shape: tuple[int, int],
) -> tuple[int, int, int, int]:
    working_height, working_width = working_shape
    original_width = int(round(working_width * scale_to_original))
    original_height = int(round(working_height * scale_to_original))
    xs = [point[0] * scale_to_original for point in points]
    ys = [point[1] * scale_to_original for point in points]
    padding = BBOX_PADDING_ORIGINAL
    x0 = int(round(min(xs) - padding))
    y0 = int(round(min(ys) - padding))
    x1 = int(round(max(xs) + padding))
    y1 = int(round(max(ys) + padding))
    x0 = max(0, min(x0, max(0, original_width - 1)))
    y0 = max(0, min(y0, max(0, original_height - 1)))
    x1 = max(x0 + 1, min(x1, original_width))
    y1 = max(y0 + 1, min(y1, original_height))
    return (x0, y0, x1 - x0, y1 - y0)


def _similarity_from_distances(distances: list[float]) -> float:
    if not distances:
        return 0.0
    median_distance = float(np.median(distances))
    return max(0.0, min(1.0, 1.0 - (median_distance / 256.0)))
