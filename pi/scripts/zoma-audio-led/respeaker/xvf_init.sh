#!/usr/bin/env bash
# ZoMa Pi audio/LED -- reSpeaker XVF3800 bring-up: DSP firmware reboot + AEC init.
# Property of TheMechanics. Contact: mamau.mechanics@gmail.com
#
# Runs at every boot (before the audio/LED services start) and is also
# re-invoked on demand by reset_respeaker.sh after a capture failure.
#
# Rebooting the XVF3800's onboard DSP firmware (`xvf_host REBOOT 1`) is the
# only reliable way to clear a wedged capture state on this device -- USB-
# level resets (unbind/bind, VBUS power-cycle, driver reload) do not reach
# it, since the wedge lives in the DSP's own firmware state, not the Linux
# USB stack. Running REBOOT 1 unconditionally on every boot, before
# anything tries to use the mic, avoids the race entirely rather than only
# recovering from it after the fact. Safe to run on an already-healthy
# device too.
#
# Does not require sudo/root -- xvf_host talks to the device over its
# existing USB HID control interface.

set -euo pipefail

# Set this to the reSpeaker vendor SDK's install path on your Pi.
BIN_DIR="${RESPEAKER_SDK_DIR:-$HOME/reSpeaker_XVF3800_USB_4MIC_ARRAY/host_control/rpi_64bit}"
CARD_NAME="Array"
REENUM_MAX_TRIES=20   # 20 * 0.5s = 10s max wait

echo "$(date '+%Y-%m-%d %H:%M:%S') [XVF_INIT] Triggering XMOS firmware reboot..."
"$BIN_DIR/xvf_host" REBOOT 1 || true

echo "$(date '+%Y-%m-%d %H:%M:%S') [XVF_INIT] Waiting for card '$CARD_NAME' to drop off after reboot..."
tries=0
while grep -q "$CARD_NAME" /proc/asound/cards 2>/dev/null; do
    sleep 0.2
    tries=$((tries + 1))
    if [ "$tries" -ge 25 ]; then
        # 25 * 0.2s = 5s -- if it never even drops, the reboot command
        # likely had no effect. Don't hang forever -- fall through and let
        # the re-enumeration check below do the real verification instead.
        echo "$(date '+%Y-%m-%d %H:%M:%S') [XVF_INIT] WARNING: card never dropped off -- proceeding anyway"
        break
    fi
done

echo "$(date '+%Y-%m-%d %H:%M:%S') [XVF_INIT] Waiting for card '$CARD_NAME' to re-enumerate..."
tries=0
until grep -q "$CARD_NAME" /proc/asound/cards 2>/dev/null; do
    sleep 0.5
    tries=$((tries + 1))
    if [ "$tries" -ge "$REENUM_MAX_TRIES" ]; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') [XVF_INIT] ERROR: card did not reappear within $((REENUM_MAX_TRIES / 2))s"
        exit 1
    fi
done
echo "$(date '+%Y-%m-%d %H:%M:%S') [XVF_INIT] Card re-enumerated after ~$((tries * 5))00ms"

sleep 1

echo "$(date '+%Y-%m-%d %H:%M:%S') [XVF_INIT] Applying DSP AEC parameters..."
"$BIN_DIR/xvf_host" AEC_FAR_EXTGAIN 0
"$BIN_DIR/xvf_host" AUDIO_MGR_SYS_DELAY 0
"$BIN_DIR/xvf_host" PP_DTSENSITIVE 0
"$BIN_DIR/xvf_host" PP_ATTNS_MODE 1
"$BIN_DIR/xvf_host" PP_ATTNS_SLOPE 5.0

echo "$(date '+%Y-%m-%d %H:%M:%S') [XVF_INIT] ReSpeaker ready."
