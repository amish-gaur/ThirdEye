# ReID cross-camera fixtures

These tests need person crops captured from at least two different
cameras to verify the day-1 demo invariant: same person across cams
clusters tighter than different people.

Required filenames (drop into this directory):

    person_A_cam1.jpg   # person A as seen from camera 1
    person_A_cam2.jpg   # same person A from camera 2
    person_B_cam1.jpg   # different person B from camera 1
    person_B_cam2.jpg   # (optional) person B from camera 2

Each crop should be a tight bounding box around the full body if
possible (head to feet), 200-1000 px tall.

## Generating fixtures from demo footage

Use the helper at `scripts/build_reid_fixtures.py` once footage exists
in `data/demo/cam_*.mp4`.

    .venv/bin/python scripts/build_reid_fixtures.py \
        --video data/demo/cam_1.mp4 --label person_A_cam1 \
        --time 12.5 --bbox 220,80,360,420

Pick the timestamp + bbox by scrubbing through the footage in any
video player. The bbox is `x1,y1,x2,y2` in pixels.
