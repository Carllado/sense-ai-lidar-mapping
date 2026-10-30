#!/usr/bin/env python3
"""Experimental geometric localization for Sense AI.

Uses the V2 change detector's verified angular-summary data.
For object removal, reports the formerly visible (near) surface.
For object addition, reports the newly visible (near) surface.
Positions are local LiDAR frame estimates, not identified object centers.
Assumes clockwise-positive measured angles; confirm device mounting
before mapping these coordinates to a compass or physical room layout.
"""
import argparse
import csv
import math
import statistics
from pathlib import Path

from sense_ai_change_detector_v2 import load_data, analyze

HERE = Path(__file__).resolve().parent


def circular_mean_degrees(angles):
    radians = [math.radians(a) for a in angles]
    x = sum(math.cos(a) for a in radians)
    y = sum(math.sin(a) for a in radians)
    return math.degrees(math.atan2(y, x)) % 360


def main():
    parser = argparse.ArgumentParser(description="Estimate locations of range-change clusters")
    parser.add_argument('--csv', type=Path, default=HERE/'sense_ai_room_ab_angular_summary.csv')
    parser.add_argument('--threshold-mm', type=float, default=100.0)
    parser.add_argument('--min-bins', type=int, default=3)
    args = parser.parse_args()
    if not math.isfinite(args.threshold_mm) or args.threshold_mm < 0 or not 1 <= args.min_bins <= 360:
        parser.error('Threshold must be finite and nonnegative; min-bins must be 1..360')
    readings = load_data(args.csv)
    _, _, regions = analyze(readings, args.threshold_mm, args.min_bins)
    rows = []
    for region in regions:
        angles = region['angles']
        angle = circular_mean_degrees(angles)
        deltas = [readings[a][2] for a in angles]
        # A positive change indicates the closer surface was in the before scan;
        # a negative change indicates the closer surface was in the after scan.
        closer = [readings[a][0] if readings[a][2] > 0 else readings[a][1] for a in angles]
        radius = statistics.median(closer)
        rad = math.radians(angle)
        x = radius * math.cos(rad)
        y = -radius * math.sin(rad)
        # Approximate angular footprint rather than a measured object width.
        angular_span_deg = len(angles)  # 1° bins
        arc_width_mm = radius * math.radians(angular_span_deg)
        rows.append({
            'region': region['region'],
            'angles_deg': f"{region['start_deg']}..{region['end_deg']}",
            'bins': len(angles),
            'change_mm': round(statistics.median(deltas), 1),
            'local_center_angle_deg': round(angle, 1),
            'near_surface_range_mm': round(radius, 1),
            'x_local_mm': round(x, 1),
            'y_local_mm': round(y, 1),
            'approx_angular_footprint_mm': round(arc_width_mm, 1),
        })
    out = HERE/'outputs'/'sense_ai_localized_regions.csv'
    out.parent.mkdir(exist_ok=True)
    with out.open('w', newline='') as f:
        if rows:
            writer=csv.DictWriter(f,fieldnames=list(rows[0]))
            writer.writeheader(); writer.writerows(rows)
        else:
            f.write('region,angles_deg,bins,change_mm,local_center_angle_deg,near_surface_range_mm,x_local_mm,y_local_mm,approx_angular_footprint_mm\n')
    print(f'Detected regions: {len(rows)}')
    for row in rows:
        print(f"  Region {row['region']} [{row['angles_deg']}°]: "
              f"angle {row['local_center_angle_deg']}°, near range {row['near_surface_range_mm']} mm; "
              f"(x,y)=({row['x_local_mm']}, {row['y_local_mm']}) mm; "
              f"approx arc footprint {row['approx_angular_footprint_mm']} mm")
    print('Saved:',out)
    print('Caution: Surface locations, not object centroids or classified identities.')

if __name__=='__main__': main()
