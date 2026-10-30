# Engineering log — October 28–29, 2026

**Project:** Sense AI — RPLIDAR C1M1 stationary mapping and object-change detection.

## Objective

Build a verified pipeline to acquire LiDAR samples, quantify range behavior, visualize a stationary 2D environment, and detect differences between scans.

## Equipment and methods

- SLAMTEC RPLIDAR C1M1, original USB serial adapter, MacBook.
- SLAMTEC SDK `ultra_simple`, USB serial 460800 baud, Python V3 logger.
- 120-second continuous warm-up, discarded before each capture.
- 5/10/20-second capture sessions with SDK SIGINT clean shutdown.
- CSV range+angle data; convert to local Cartesian coordinates.
- Robust angular representation: median positive range per 1° bin.

## Measured results

1. Stationary reference-range tests: 500 ±3 mm → 495.06 mm mean; 1000 ±3 mm → 991.56 mm mean; 2000 ±10 mm → 1982.58 mm mean. The latter central sector and uncertainty differ from earlier tests. Values refer to selected target sectors, not full-scan means.
2. Book-present/removed: roughly 1982 mm → 2276 mm at about 353°. Positive change ~294 mm. V2 kept a 5-bin cluster at 351°–355° and an unexplained 3-bin cluster near 224°–226°.
3. At 100 and 150 mm thresholds with ≥3 neighboring bins, both clusters survived.
4. An intentional laptop setup change altered nearby distances near 169°–171° by >500 mm. It changed both the cover's presence and laptop height, so their individual contributions cannot be isolated.
5. Stationary laptop-on-floor repeat: 350 bins comparable; median absolute difference 1 mm, 90th percentile 5 mm; 0 V2 clusters after spatial filtering at both thresholds.

## Engineering concepts learned

Polar range/angle and Cartesian conversion; UART baud rate vs sensor acquisition; measurement accuracy vs repeatability; uncertainty; angular segmentation and wraparound; scene/background subtraction; thresholds and spatial consistency; false alarms vs true scene changes; sensor coordinate frame vs room frame.

## Caveats and unverified items

- The 224°–226° candidate change was not conclusively explained.
- The small no-change test is not a statistically sound false-alarm-rate estimate.
- The triangular mark and exact physically calibrated zero-angle reference have not been verified to precision; exploratory placement supported a 90° relative angle shift.
- This is stationary environmental mapping, **not SLAM**, object classification, camera/LiDAR sensor fusion, or autonomous navigation.
- Legacy logger JSON fields for reference distance and candidate angular sector sometimes carried defaults and should not be treated as ground truth for other conditions.

## Next milestone / acceptance criteria

Create a local-coordinate report for each V2 cluster from the earlier near surface: angle, median range, x/y, approximate angular footprint, and a saved CSV. Validate that the known book cluster remains and the report includes explicit limitations. Afterwards, publish reproducible code+plots+experimental notes to GitHub.
