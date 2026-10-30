#!/usr/bin/env python3
"""Sense AI Change Detector V2.

Compares 1-degree median LiDAR ranges from two stationary scans.
Uses only the Python standard library (Python 3.9+).
Detects angular clusters with wraparound and exports CSV + interactive SVG.

Important: detects range changes, not object identities, motion, or SLAM.
"""
from __future__ import annotations

import argparse
import csv
import html
import math
import statistics
from pathlib import Path

BASE = Path(__file__).resolve().parent
SOURCE = BASE / 'sense_ai_room_ab_angular_summary.csv'


def maybe_float(s):
    try:
        n = float(s)
        return n if math.isfinite(n) and n > 0 else None
    except (ValueError, TypeError):
        return None


def load_data(path):
    readings = {}  # angle: (before, after, delta) or None
    with path.open(newline='', encoding='utf-8-sig') as stream:
        reader = csv.DictReader(stream)
        needed = {'angle_bin_deg', 'book_present_median_mm', 'book_removed_median_mm'}
        if not needed.issubset(reader.fieldnames or []):
            raise ValueError('CSV is missing required columns: ' + ', '.join(sorted(needed)))
        for row in reader:
            try:
                angle_float = float(row['angle_bin_deg'])
            except (TypeError, ValueError):
                continue
            if not angle_float.is_integer() or not 0 <= angle_float < 360:
                continue
            angle = int(angle_float)
            before = maybe_float(row['book_present_median_mm'])
            after = maybe_float(row['book_removed_median_mm'])
            readings[angle] = (before, after, after - before) if before is not None and after is not None else None
    return readings


def circular_clusters(flagged):
    """Group neighboring integer angles; combine 359° and 0° when necessary."""
    clusters = []
    for angle in sorted(flagged):
        if clusters and angle == clusters[-1][-1] + 1:
            clusters[-1].append(angle)
        else:
            clusters.append([angle])
    if len(clusters) > 1 and clusters[0][0] == 0 and clusters[-1][-1] == 359:
        clusters[0] = clusters[-1] + clusters[0]  # e.g. [358,359,0,1]
        clusters.pop()
    return clusters


def analyze(readings, threshold, min_bins):
    flagged = {a: v[2] for a, v in readings.items() if v is not None and abs(v[2]) > threshold}
    all_clusters = circular_clusters(flagged)
    kept = [c for c in all_clusters if len(c) >= min_bins]
    records = []
    for ix, cluster in enumerate(kept, 1):
        diffs = [flagged[a] for a in cluster]
        median_diff = statistics.median(diffs)
        records.append({'region': ix, 'start_deg': cluster[0], 'end_deg': cluster[-1],
                        'bins': len(cluster), 'median_change_mm': median_diff,
                        'classification': 'farther (possible removal)' if median_diff > 0 else 'nearer (possible addition)',
                        'angles': cluster})
    return flagged, all_clusters, records


def save_report(records, path):
    names = ['region', 'start_deg', 'end_deg', 'bins', 'median_change_mm', 'classification']
    with path.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=names)
        writer.writeheader()
        for record in records:
            writer.writerow({k: record[k] for k in names})


def make_svg(readings, records, threshold, min_bins, path):
    """Create a standalone SVG: room point-cloud overlay + angular difference."""
    W, H = 1120, 650
    # Top-down plot: clockwise-positive LiDAR direction, so y = -r*sin(theta).
    cx, cy, scale = 290, 315, 0.095  # 2.5m = 237.5 px
    active = {}
    for r in records:
        for a in r['angles']:
            active[a] = r['region']
    def pos(a, r):
        t = math.radians(a)
        return cx + scale * r * math.cos(t), cy + scale * r * math.sin(t)
    def circ(x, y, rad, color, opacity=1, stroke='none', sw=0):
        return f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{rad}" fill="{color}" fill-opacity="{opacity}" stroke="{stroke}" stroke-width="{sw}"/>'
    def line(x1,y1,x2,y2, color, sw=1, dash=''):
        return f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{color}" stroke-width="{sw}" {dash}/>'
    def text(x,y,s,size=12,color='#334155',weight=400,anchor='start'):
        return f'<text x="{x}" y="{y}" font-family="Arial,sans-serif" font-size="{size}" fill="{color}" font-weight="{weight}" text-anchor="{anchor}">{html.escape(s)}</text>'
    s = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">',
         '<rect width="100%" height="100%" fill="#ffffff"/>',
         text(30,35,'Sense AI | Change Detector V2',23,'#0f172a',700),
         text(30,58,f'Range-change threshold: {threshold:g} mm   •   Minimum cluster width: {min_bins} bins   •   Stationary LiDAR scans',13),
         text(cx,86,'Top-down range map (sensor at origin)',16,'#0f172a',700,'middle'),
         text(760,86,'Distance change by angle',16,'#0f172a',700,'middle')]
    for mm in (500, 1000, 1500, 2000, 2500):
        s.append(circ(cx,cy,scale*mm,'none',1,'#e2e8f0',1))
        s.append(text(cx+scale*mm+2,cy-4,f'{mm/1000:g}m',10,'#94a3b8'))
    s.extend([line(cx-250,cy,cx+250,cy,'#cbd5e1'), line(cx,cy-250,cx,cy+250,'#cbd5e1')])
    for a, v in sorted(readings.items()):
        if v is None: continue
        b, after, delta = v
        x,y=pos(a,b)
        s.append(circ(x,y,2.7,'#2563eb',.42))
        x,y=pos(a,after)
        s.append(circ(x,y,2.7,'#0f766e',.50))
    for a, rid in sorted(active.items()):
        v=readings[a]
        if v is None: continue
        b, after, d = v
        x1,y1=pos(a,b); x2,y2=pos(a,after)
        color = '#e11d48' if d > 0 else '#f59e0b'
        s.append(line(x1,y1,x2,y2,color,2.8))
        s.append(circ(x2,y2,4.0,color,.95,'white',.8))
    s.append(circ(cx,cy,5.2,'#0f172a'))
    s.extend([text(65,576,'Blue: book present',13,'#2563eb',700),text(255,576,'Teal: book removed',13,'#0f766e',700),
              text(65,596,'Pink: farther  •  Amber: nearer',12)])
    # Difference chart in right side
    left,right,top,bottom = 610,1080,138,515
    ymax = 950
    mid = (top+bottom)/2
    s.extend([line(left,mid,right,mid,'#94a3b8',1.3),line(left,top,left,bottom,'#cbd5e1')])
    for n in (-800,-400,0,400,800):
        y = mid-(n/ymax)*(bottom-top)/2
        s.append(line(left,y,right,y,'#edf2f7',1))
        s.append(text(left-10,int(y+4),f'{n:+d}' if n else '0',11,'#64748b',400,'end'))
    for n in (0,90,180,270,359):
        x=left+n/359*(right-left)
        s.append(line(x,top,x,bottom,'#f1f5f9',1))
        s.append(text(int(x),bottom+20,str(n)+'°',11,'#64748b',400,'middle'))
    for v in (threshold,-threshold):
        y=mid-(v/ymax)*(bottom-top)/2
        s.append(line(left,y,right,y,'#b45309',1,'stroke-dasharray="4 4"'))
    for a, v in sorted(readings.items()):
        if v is None:continue
        d=v[2]
        x=left+a/359*(right-left)
        y=mid-(max(-ymax,min(ymax,d))/ymax)*(bottom-top)/2
        color = '#e11d48' if d>0 else '#f59e0b'
        op = '1' if a in active else '.22'
        s.append(f'<line x1="{x:.2f}" y1="{mid:.2f}" x2="{x:.2f}" y2="{y:.2f}" stroke="{color}" stroke-width="2" stroke-opacity="{op}"/>')
    s.extend([text(845,top-20,'Δr = removed − present (mm)',12,'#334155',400,'middle'),
              text(845,548,'Angle (degrees)',12,'#64748b',400,'middle')])
    for r in records:
        loc = f"{r['start_deg']}°–{r['end_deg']}°"
        s.append(text(630,580+21*(r['region']-1),f"Region {r['region']}: {loc}, {r['median_change_mm']:+g} mm",12,
                      '#e11d48' if r['median_change_mm']>0 else '#b45309',700))
    s.append(text(30,630,'Median 1° bins, not a full SLAM map. Differences may include occlusion, people, motion, or reflective effects.',11,'#64748b'))
    s.append('</svg>')
    path.write_text('\n'.join(s),encoding='utf-8')


def main():
    parser=argparse.ArgumentParser(description='Sense AI: angular LiDAR change detector V2')
    parser.add_argument('--threshold-mm',type=float,default=100.,help='Absolute range-change threshold (default 100)')
    parser.add_argument('--min-bins',type=int,default=3,help='Minimum consecutive angular bins (default 3)')
    parser.add_argument('--csv',type=Path,default=SOURCE,help='Input angular summary CSV')
    args=parser.parse_args()
    if not math.isfinite(args.threshold_mm) or args.threshold_mm < 0:
        parser.error('--threshold-mm must be a finite nonnegative value')
    if not 1 <= args.min_bins <= 360:
        parser.error('--min-bins must be between 1 and 360')
    if not args.csv.is_file():
        parser.error(f'CSV not found: {args.csv}')
    readings=load_data(args.csv)
    flagged, all_clusters, records = analyze(readings,args.threshold_mm,args.min_bins)
    outdir = BASE / 'outputs'
    outdir.mkdir(exist_ok=True)
    report=outdir/'sense_ai_v2_detected_regions.csv'
    svg=outdir/'sense_ai_v2_change_map.svg'
    save_report(records,report)
    make_svg(readings,records,args.threshold_mm,args.min_bins,svg)
    print(f'CSV: {args.csv}')
    print(f'Comparable angular bins: {sum(v is not None for v in readings.values())} / 360')
    print(f'Threshold: |removed - present| > {args.threshold_mm:g} mm')
    print(f'Minimum width: {args.min_bins} consecutive 1-degree bins')
    print(f'Flagged bins before width filter: {len(flagged)}')
    print(f'Regions before filter: {len(all_clusters)}')
    print(f'Regions after filter: {len(records)}')
    for r in records:
        print(f"  {r['region']}. {r['start_deg']}° to {r['end_deg']}° "
              f"({r['bins']} bins): median {r['median_change_mm']:+.1f} mm; {r['classification']}")
    print(f'\nSaved report: {report}')
    print(f'Saved visualization: {svg}')
    print('Open SVG on Mac: open outputs/sense_ai_v2_change_map.svg')
    print('These are geometric changes; not identified objects or proven causes.')


if __name__ == '__main__':
    main()
