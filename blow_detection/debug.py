"""Live debug window for MediaPipe blow detection.

Shows webcam feed with mouth ratio overlaid. Press Q to quit.

Usage:
  .venv/bin/python blow_detection/debug.py
  .venv/bin/python blow_detection/debug.py --threshold 0.45 --camera 1
"""

import argparse
import os
import time
import cv2
import mediapipe as mp

_MOUTH_L, _MOUTH_R = 61, 291
_EYE_L,   _EYE_R   = 33, 263
_MODEL = os.path.join(os.path.dirname(__file__), "face_landmarker.task")

FaceLandmarker = mp.tasks.vision.FaceLandmarker
FaceLandmarkerOptions = mp.tasks.vision.FaceLandmarkerOptions
RunningMode = mp.tasks.vision.RunningMode

_READY   = "ready"
_BLOWING = "blowing"


def _dist(a, b):
    return ((a.x - b.x) ** 2 + (a.y - b.y) ** 2) ** 0.5


def run(camera_index: int, threshold: float, min_frames: int):
    cap = cv2.VideoCapture(camera_index)
    if not cap.isOpened():
        print(f"Cannot open camera {camera_index}")
        return

    options = FaceLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=_MODEL),
        running_mode=RunningMode.IMAGE,
        num_faces=1,
    )
    landmarker = FaceLandmarker.create_from_options(options)

    state = _READY
    consecutive = 0
    blow_flash_until = 0.0

    print(f"Camera {camera_index} | threshold={threshold} | min_frames={min_frames}")
    print("Press Q to quit, +/- to adjust threshold")

    while True:
        ok, frame = cap.read()
        if not ok:
            continue

        frame = cv2.flip(frame, 1)
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        result = landmarker.detect(mp_image)

        ratio = 0.0
        fired = False
        h_px, w_px = frame.shape[:2]

        nw = 1.0
        if result.face_landmarks:
            lm = result.face_landmarks[0]
            mouth_w = _dist(lm[_MOUTH_L], lm[_MOUTH_R])
            face_w  = _dist(lm[_EYE_L],   lm[_EYE_R])
            nw = mouth_w / face_w if face_w > 0 else 1.0
            pursed = nw <= threshold

            # State machine
            if state == _READY:
                consecutive = consecutive + 1 if pursed else 0
                if consecutive >= min_frames:
                    state = _BLOWING
                    consecutive = 0
                    fired = True
                    blow_flash_until = time.time() + 0.4
                    print(f"BLOW  nw={nw:.3f}  threshold={threshold:.2f}")
            elif state == _BLOWING:
                if not pursed:  # mouth relaxed → back to ready
                    state = _READY
                    consecutive = 0

            # Draw mouth corners and eye corners
            dot_color = (60, 100, 255) if state == _BLOWING else (180, 160, 255)
            for idx in [_MOUTH_L, _MOUTH_R, _EYE_L, _EYE_R]:
                pt = lm[idx]
                cx, cy = int(pt.x * w_px), int(pt.y * h_px)
                cv2.circle(frame, (cx, cy), 4, dot_color, -1)
            # Line between mouth corners to visualise width
            ml = lm[_MOUTH_L]; mr = lm[_MOUTH_R]
            cv2.line(frame,
                     (int(ml.x * w_px), int(ml.y * h_px)),
                     (int(mr.x * w_px), int(mr.y * h_px)),
                     dot_color, 2)
        else:
            consecutive = 0
            if state == _BLOWING:
                state = _READY

        # ── HUD ──────────────────────────────────────────────────
        # Bar shows normalized_width — bar is FULL at rest, SHRINKS when pursing
        bar_x, bar_y, bar_w, bar_h = 16, 16, 220, 28
        cv2.rectangle(frame, (bar_x, bar_y), (bar_x + bar_w, bar_y + bar_h), (40, 40, 40), -1)
        fill = int(min(nw / 0.8, 1.0) * bar_w)
        bar_color = (60, 100, 255) if state == _BLOWING else (60, 220, 100)
        cv2.rectangle(frame, (bar_x, bar_y), (bar_x + fill, bar_y + bar_h), bar_color, -1)
        thresh_x = bar_x + int((threshold / 0.8) * bar_w)
        cv2.line(frame, (thresh_x, bar_y), (thresh_x, bar_y + bar_h), (255, 255, 255), 2)
        cv2.putText(frame, f"mouth/face {nw:.3f}  thresh {threshold:.2f}",
                    (bar_x + 4, bar_y + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (255, 255, 255), 1)

        # State label
        state_color = (60, 100, 255) if state == _BLOWING else (160, 200, 160)
        cv2.putText(frame, f"state: {state}  onset: {consecutive}/{min_frames}",
                    (bar_x, bar_y + 50), cv2.FONT_HERSHEY_SIMPLEX, 0.45, state_color, 1)

        cv2.putText(frame, "+/- threshold   Q quit",
                    (bar_x, h_px - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (160, 160, 160), 1)

        # BLOW flash (shown for 0.4s after onset)
        if time.time() < blow_flash_until:
            cv2.rectangle(frame, (0, 0), (w_px, h_px), (60, 100, 255), 8)
            cv2.putText(frame, "BLOW", (w_px // 2 - 55, h_px - 40),
                        cv2.FONT_HERSHEY_DUPLEX, 2.2, (60, 100, 255), 3)

        cv2.imshow("Blow Detector — debug", frame)

        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break
        elif key == ord('+') or key == ord('='):
            threshold = round(threshold + 0.02, 3)
            print(f"threshold → {threshold}")
        elif key == ord('-'):
            threshold = round(max(0.05, threshold - 0.02), 3)
            print(f"threshold → {threshold}")

    cap.release()
    landmarker.close()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--min-frames", type=int, default=3)
    args = parser.parse_args()
    run(args.camera, args.threshold, args.min_frames)
