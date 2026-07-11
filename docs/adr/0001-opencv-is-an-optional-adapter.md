# OpenCV is an informed optional adapter

OpenCV may improve local-change, color, edge, and motion scoring, but making its large Python wheel mandatory would weaken the original skill's easy, self-contained installation. Keep FFmpeg plus standard-library Python as the default adapter; explain the measured tradeoffs during setup and let installers explicitly opt into OpenCV, with deterministic fallback whenever it is absent or fails.
