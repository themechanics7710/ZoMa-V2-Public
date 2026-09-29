# ZoMa Pi ROS 2 container -- Humble on Ubuntu 22.04 (arm64), used to run the
# micro-ROS agent that bridges esp32_rx's deploy_ros firmware to the Pi, and
# to run the wifi/audio HUD diagnostic ROS 2 nodes (see
# pi/scripts/zoma-audio-led/wifi_diag_publisher.py, audio_diag_publisher.py).
# Property of TheMechanics. Contact: mamau.mechanics@gmail.com
#
# Reconstructed to match the runtime characteristics of the container this
# build actually runs (base distro, entrypoint behavior, packages inferred
# from what's used against it), not copied from an original Dockerfile --
# none was preserved. If you have your own, use it instead; this one exists
# so the build doesn't depend on undocumented infrastructure. See
# docs/STARTUP_GUIDE.md for how it's built and run.

FROM ros:humble-ros-base

RUN apt-get update && apt-get install -y --no-install-recommends \
    ros-humble-micro-ros-agent \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Keeps the container alive for `docker exec` rather than running a single
# foreground process -- start_zoma_audio_hud_pi.sh docker cp's a diagnostics
# script in and execs it here on demand.
CMD ["tail", "-f", "/dev/null"]
