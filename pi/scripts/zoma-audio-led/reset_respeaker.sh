#!/bin/bash
# ZoMa Pi audio/LED -- recovery wrapper that re-triggers reSpeaker DSP reset/init.
# Property of TheMechanics. Contact: mamau.mechanics@gmail.com
#
# Called by zoma_mic_client.py's recovery path after repeated fast arecord
# failures. The actual reset logic (DSP firmware reboot, re-enumeration
# wait, AEC parameter init) lives in xvf_init.sh, which also runs
# proactively at every boot via its own systemd unit -- this script just
# re-invokes that same logic on demand.

# Set this to the reSpeaker vendor SDK's install path on your Pi.
RESPEAKER_SDK_DIR="${RESPEAKER_SDK_DIR:-$HOME/reSpeaker_XVF3800_USB_4MIC_ARRAY/host_control/rpi_64bit}"

set -e
exec "$RESPEAKER_SDK_DIR/xvf_init.sh"
