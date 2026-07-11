# OpenCV is an informed optional adapter

OpenCV may improve local-change, color, edge, and motion scoring, but making its large Python wheel mandatory would weaken the original skill's easy, self-contained installation. Keep FFmpeg plus standard-library Python as the default adapter; explain the measured tradeoffs during setup and let installers explicitly opt into OpenCV, with deterministic fallback whenever it is absent or fails.

Update (2026-07-11): the informed-choice intent is satisfied by a documented environment-variable opt-in (`WATCH_VISION_BACKEND=opencv` plus a one-line install command, with measured tradeoff numbers in the documentation) rather than an interactive setup prompt, until the Milestone C ablation in [plans/EVIDENCE-BACKED-IMPROVEMENT-PLAN-V2.md](../plans/EVIDENCE-BACKED-IMPROVEMENT-PLAN-V2.md) justifies the fuller installer.
