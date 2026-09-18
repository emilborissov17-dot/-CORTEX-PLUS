#!/bin/sh
# tools/sandbox/fence.sh — THE NETWORK FENCE FOR THE omega USER.
#
# Installed at /usr/local/sbin/omega-fence.sh and run at every WSL start by
# /etc/wsl.conf [boot] command=. Idempotent: it flushes its own chain first, so
# running it twice leaves one copy of each rule.
#
# WHAT IT ALLOWS, AND NOTHING ELSE
# --------------------------------
# uid omega may open exactly one destination: 127.0.0.1 tcp/11434, the Ollama
# that runs inside this distro. Every other packet omega sends is REJECTED.
#
# WHY NOT "ACCEPT ALL OF 127.0.0.1", which is the obvious rule to write: this
# VM is not empty. Measured on 2026-09-18 with `ss -lntp`, loopback also carries
#
#     127.0.0.1:18789  openclaw-gateway   <- the OpenClaw bridge
#     127.0.0.1:18791  openclaw-gateway
#     127.0.0.1:18792  openclaw-gateway
#     127.0.0.1:44571  containerd
#     127.0.0.54:53    systemd-resolve
#
# An agent that reads untrusted text and can reach the OpenClaw gateway on
# loopback has a shell by another road, and the whole point of this sandbox is
# that it must not. So loopback is allowed BY PORT, not by address, and the
# four ports above are additionally rejected by name in their own rules, above
# the catch-all, so that `iptables -L` reads as an intention rather than as a
# side effect of ordering.
#
# WHY REJECT AND NOT DROP. DROP makes a fenced call hang until its timeout and
# look like a slow network; REJECT answers immediately and the caller prints a
# refusal a human can read. The project rule is fail loud, and a probe that
# times out proves less than a probe that is refused: a timeout is also what a
# dead host looks like.
#
# WHAT THIS DOES NOT DO. It is an OUTPUT filter keyed on uid. It does not stop
# root, it does not stop any other user, and a process that changes uid is out
# of its scope by construction. It is one layer; see the report's
# "what this sandbox does NOT protect against".
#
# Verify:  iptables -L OMEGA_FENCE -n -v --line-numbers
# Probe:   tools/sandbox/check.sh  (P1, P2, P10)
set -e

IPT=/usr/sbin/iptables
USER_NAME=omega
OLLAMA_ADDR=127.0.0.1
OLLAMA_PORT=11434
CHAIN=OMEGA_FENCE

# The user may not exist yet on a boot that precedes Step 1. Say so and stop;
# installing a fence for a uid that is not there would look installed and guard
# nothing, which is worse than refusing.
if ! id "$USER_NAME" >/dev/null 2>&1; then
    echo "omega-fence: user '$USER_NAME' does not exist — no fence installed" >&2
    exit 1
fi
UID_OMEGA=$(id -u "$USER_NAME")

# Own chain, so flushing cannot touch anybody else's OUTPUT rules.
$IPT -N "$CHAIN" 2>/dev/null || true
$IPT -F "$CHAIN"

# --- the one thing omega may reach -----------------------------------------
$IPT -A "$CHAIN" -o lo -p tcp -d "$OLLAMA_ADDR" --dport "$OLLAMA_PORT" -j ACCEPT

# --- named refusals, above the catch-all, so the intent is readable ---------
# These are already covered by the final REJECT. They are spelled out because a
# reader of the rule list should not have to reconstruct which loopback
# services exist on this host to know they were considered.
for PORT in 18789 18791 18792 44571; do
    $IPT -A "$CHAIN" -p tcp --dport "$PORT" -j REJECT --reject-with tcp-reset
done
$IPT -A "$CHAIN" -p tcp --dport 53 -j REJECT --reject-with tcp-reset
$IPT -A "$CHAIN" -p udp --dport 53 -j REJECT --reject-with icmp-port-unreachable

# --- everything else -------------------------------------------------------
$IPT -A "$CHAIN" -p tcp -j REJECT --reject-with tcp-reset
$IPT -A "$CHAIN" -j REJECT --reject-with icmp-port-unreachable

# Jump into the chain for this uid only. Deleted first so a re-run does not
# stack a second jump above the first.
$IPT -D OUTPUT -m owner --uid-owner "$UID_OMEGA" -j "$CHAIN" 2>/dev/null || true
$IPT -I OUTPUT 1 -m owner --uid-owner "$UID_OMEGA" -j "$CHAIN"

echo "omega-fence: installed for uid $UID_OMEGA ($USER_NAME); allowed $OLLAMA_ADDR:$OLLAMA_PORT only"
