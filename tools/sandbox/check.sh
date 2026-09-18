#!/bin/bash
# tools/sandbox/check.sh — PROVE THE FENCE, DO NOT ASSERT IT.
#
# Runs inside WSL2 Ubuntu as root. Every probe executes as the omega user via
# `su - omega -c` and PRINTS THE ACTUAL OUTPUT LINE. There is no PASS word
# anywhere in this file for a guard that was not exercised: the project rule is
# that a guard is proven by a run that tries to break it and shows the refusal,
# so each probe states what it expected and then shows what the system said.
#
# A probe that fails STOPS the run (set -e is NOT used; the stop is explicit and
# named, so the report says which probe stopped it). The fence is never weakened
# to make a probe pass.
#
# Usage (from Windows):  tools\sandbox_check.ps1
# Usage (inside Ubuntu): sudo bash tools/sandbox/check.sh
set -u

OMEGA_HOME=/home/omega
OMEGA_DIR=$OMEGA_HOME/omega
SCRATCH=$OMEGA_HOME/scratch
VENV=$OMEGA_HOME/venv/bin/python
# omega talks to the PROXY, never to Ollama. The real port is named separately
# because P12 has to prove it is now unreachable, which needs its address.
PROXY=127.0.0.1:11435
REAL_OLLAMA=127.0.0.1:11434
PROXY_LOG=/var/log/omega-proxy.jsonl
MARKER=$SCRATCH/P9_MARKER_MUST_NOT_EXIST
FAILED=""

say()  { printf '\n=== %s ===\n' "$*"; }
out()  { printf '    %s\n' "$@"; }
asomega() { su - omega -c "$1" 2>&1; }

fail() {
    printf '\n!!! %s FAILED: %s\n' "$1" "$2"
    printf '!!! stopping. The fence is NOT weakened to make a probe pass.\n'
    exit 1
}

if [ "$(id -u)" != "0" ]; then
    echo "check.sh must run as root (it uses su - omega)"; exit 2
fi
if ! id omega >/dev/null 2>&1; then
    echo "check.sh: user omega does not exist — Step 1 has not been run"; exit 2
fi

printf 'SANDBOX CHECK  %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
printf 'host uname: %s\n' "$(uname -srm)"
printf 'fence rules in force:\n'
iptables -L OMEGA_FENCE -n --line-numbers | sed 's/^/    /'

# --------------------------------------------------------------------- P1
say "P1  outbound internet as omega must be REFUSED"
R=$(asomega "curl -sS -m 5 https://example.com")
out "$ curl -m 5 https://example.com" "$R"
case "$R" in
    *"Could not resolve host"*|*"Failed to connect"*|*"Connection refused"*) ;;
    *) fail P1 "outbound was not refused: $R" ;;
esac
# By NAME the refusal lands on DNS, which proves the udp/53 rule and not the
# outbound one. So ask again by raw IP, where no resolver is involved.
R1B=$(asomega "curl -sS -m 5 https://1.1.1.1/")
out "$ curl -m 5 https://1.1.1.1/   (raw IP, no DNS)" "$R1B"
case "$R1B" in
    *"Failed to connect"*|*"Connection refused"*) ;;
    *) fail P1b "raw-IP outbound was not refused: $R1B" ;;
esac
# CONTROL. If root were fenced too, P1 would prove the host has no network
# rather than that omega is fenced. This line is what makes P1 mean something.
RC=$(curl -sS -m 5 -o /dev/null -w 'HTTP %{http_code}' https://1.1.1.1/ 2>&1)
out "$ (control, as ROOT) curl -m 5 https://1.1.1.1/ -> $RC"
case "$RC" in
    HTTP\ [23]*) ;;
    *) fail P1-control "root cannot reach the network either, so P1 proves nothing: $RC" ;;
esac

# --------------------------------------------------------------------- P2
say "P2  the one allowed destination must WORK"
R=$(asomega "curl -sS -m 10 http://$PROXY/api/tags")
out "$ curl -m 10 http://$PROXY/api/tags   (through the proxy)" "$(echo "$R" | head -c 240)"
case "$R" in
    *'"models"'*) ;;
    *) fail P2 "Ollama did not answer through the fence: $R" ;;
esac
echo "$R" | grep -q 'qwen2.5:3b' || fail P2 "qwen2.5:3b is not on the endpoint"
out "qwen2.5:3b present: yes"

# --------------------------------------------------------------------- P3
say "P3  the code tree must be READ-ONLY to omega"
R=$(asomega "touch $OMEGA_DIR/x")
out "$ touch $OMEGA_DIR/x" "$R"
case "$R" in *"Permission denied"*) ;; *) fail P3 "the tree is writable: $R" ;; esac
R=$(asomega "cat $OMEGA_DIR/README.md | head -1")
out "$ head -1 $OMEGA_DIR/README.md   (read must still work)" "$R"
[ -n "$R" ] || fail P3 "omega cannot READ its own code either"

# --------------------------------------------------------------------- P4
say "P4  scratch must be WRITABLE to omega"
R=$(asomega "touch $SCRATCH/p4probe && echo CREATED: \$(ls -l $SCRATCH/p4probe) && rm $SCRATCH/p4probe")
out "$ touch $SCRATCH/p4probe" "$R"
case "$R" in *CREATED*) ;; *) fail P4 "scratch is not writable: $R" ;; esac

# --------------------------------------------------------------------- P5
say "P5  the Windows tree must be OUT OF REACH"
R=$(asomega "ls /mnt/c")
out "$ ls /mnt/c" "$R"
case "$R" in *"Permission denied"*) ;; *) fail P5 "omega can read /mnt/c: $R" ;; esac

# --------------------------------------------------------------------- P6
say "P6  no privilege escalation"
R=$(asomega "sudo -n true")
out "$ sudo -n true" "$R"
case "$R" in
    *"password is required"*|*"not in the sudoers"*|*"command not found"*) ;;
    *) fail P6 "sudo did not refuse: $R" ;;
esac
out "groups: $(groups omega)"

# --------------------------------------------------------------------- P7
say "P7  three turns recorded through Omega's own provider path"
# WHY NOT THE MOCK CHANNEL. channels/mockchannel.py:2 imports Autotests.mock.comm
# and connects to (TEST_SERVER_IP, COMM_MOCK_PORT); providers/mockprovider.py does
# the same for the LLM mock. Both are sockets to a controller the fence rejects,
# and standing one up would mean opening a hole for a test. So the dry run
# registers a stub through Omega's OWN registry — registerLLMProvider ->
# llmProviderStart -> llmProviderChat, the same three calls the agent makes — and
# the point of P7, three recorded turns through the real choke point, is kept.
cat > /tmp/omega_p7.py <<'PYEOF'
import sys, importlib.util
O = '/home/omega/omega/repos/Omega'
# providers/ is NOT put on sys.path: it contains openai.py, which shadows the
# real openai package and breaks lib_llm_ext with a circular import. PeTTa loads
# these files by path, so this driver does too.
sys.path[:0] = [O, O + '/src']
def by_path(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec); sys.modules[name] = mod
    spec.loader.exec_module(mod); return mod
import providers
llm = by_path('lib_llm_ext', O + '/providers/lib_llm_ext.py')
class StubProvider(providers.LLMProvider):
    class Impl(llm.AbstractAIProvider):
        def __init__(self): super().__init__('SandboxStub')
        def chat(self, content, max_tokens=6000, reasoning='medium', **kw):
            return 'stub reply to: ' + content[:40]
        @property
        def is_available(self): return True
        def stop(self): pass
    def start(self): self.delegate = self.Impl()
    def stop(self): self.delegate.stop()
    def chat(self, prompt, max_tokens=6000, reasoning_mode='medium'):
        return self.delegate.chat(prompt, max_tokens, reasoning_mode)
providers.registerLLMProvider('SandboxStub', StubProvider())
providers.llmProviderStart('SandboxStub')
for i in (1, 2, 3):
    print('turn %d -> %s' % (i, providers.llmProviderChat('dry run turn %d' % i, 64, 'medium')))
PYEOF
chmod 644 /tmp/omega_p7.py
asomega "rm -f $SCRATCH/turns.jsonl"
R=$(asomega "cd $OMEGA_DIR/repos/Omega && $VENV /tmp/omega_p7.py")
out "$ python omega_p7.py" "$R"
N=$(asomega "wc -l < $SCRATCH/turns.jsonl" | tr -d ' ')
out "lines in turns.jsonl: $N"
[ "$N" = "3" ] || fail P7 "expected 3 turn lines, got $N"
asomega "cat $SCRATCH/turns.jsonl" | sed 's/^/    /'

# --------------------------------------------------------------------- P8
say "P8  one real question through the local provider"
cat > /tmp/omega_p8.py <<'PYEOF'
import sys, importlib.util
O = '/home/omega/omega/repos/Omega'
sys.path[:0] = [O, O + '/src']
def by_path(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec); sys.modules[name] = mod
    spec.loader.exec_module(mod); return mod
import config
config.init_config([])
import providers
by_path('lib_llm_ext', O + '/providers/lib_llm_ext.py')
by_path('openaiapi_mod', O + '/providers/openaiapi.py').loadOmegaPlugin()
print('provider       :', config.config_get_by_key('provider'))
print('openaiapi_url  :', config.config_get_by_key('openaiapi_url'))
print('openaiapi_model:', config.config_get_by_key('openaiapi_model'))
providers.llmProviderStart('OpenAIAPI')
print('reply          :', repr(providers.llmProviderChat(
    'What is 17*3? Answer with the number only.', 64, 'medium')))
PYEOF
chmod 644 /tmp/omega_p8.py
R=$(asomega "cd $OMEGA_DIR/repos/Omega && OPENAIAPI_API_KEY=sandbox-no-key $VENV /tmp/omega_p8.py")
out "$ python omega_p8.py" "$R"
case "$R" in *"reply"*) ;; *) fail P8 "no reply from the local provider: $R" ;; esac
LAST=$(asomega "tail -1 $SCRATCH/turns.jsonl")
out "turns.jsonl last line:" "$LAST"
case "$LAST" in *'"provider": "OpenAIAPI"'*) ;; *) fail P8 "the turn was not recorded as OpenAIAPI" ;; esac
case "$LAST" in *'"model": "qwen2.5:3b"'*) ;; *) fail P8 "the turn did not record qwen2.5:3b" ;; esac
# The proxy saw the same call from the other side. Quoting both is what shows the
# turn log and the proxy log are describing one request and not two.
PL=$(tail -1 "$PROXY_LOG" 2>/dev/null)
out "proxy log last line:" "$PL"
case "$PL" in
    *'"path": "/v1/chat/completions"'*) ;;
    *) fail P8 "the proxy did not record a /v1/chat/completions call: $PL" ;;
esac

# --------------------------------------------------------------------- P9
say "P9  the shell skill must refuse, by name, and execute nothing"
cat > /tmp/omega_p9.metta <<'MEOF'
!(import! &self (library lib_import))
!(git-import! "https://github.com/singnet/Omega.git")
!(import_prolog_functions_from_file (library Omega ./src/skills.pl) (shell first_char gc read_file_tail))
!(shell "touch /home/omega/scratch/P9_MARKER_MUST_NOT_EXIST")
MEOF
chmod 644 /tmp/omega_p9.metta
asomega "rm -f $MARKER"
R=$(asomega "cd $OMEGA_DIR && timeout 180 swipl --stack_limit=2g -q -s ./src/main.pl -- /tmp/omega_p9.metta" \
    | sed 's/\x1b\[[0-9;]*m//g' | grep -i 'SANDBOX-FENCE-REFUSED')
out "refusal lines:" "$R"
case "$R" in *SANDBOX-FENCE-REFUSED*) ;; *) fail P9 "no fence refusal was printed" ;; esac
# THE PROOF IS THE ABSENCE. The refusal string could be printed by code that also
# ran the command; only the missing marker shows nothing executed.
M=$(asomega "ls -la $MARKER")
out "$ ls -la $MARKER" "$M"
case "$M" in
    *"No such file"*) out "marker absent: the command did NOT run" ;;
    *) fail P9 "THE MARKER EXISTS — the shell command executed: $M" ;;
esac

# --------------------------------------------------------------------- P10
say "P10 loopback is allowed BY PORT, not by address"
R=$(asomega "curl -sS -m 3 http://127.0.0.1:18789/")
out "$ curl -m 3 http://127.0.0.1:18789/   (OpenClaw gateway)" "$R"
case "$R" in
    *"Failed to connect"*|*"Connection refused"*) ;;
    *) fail P10 "omega reached the OpenClaw gateway on loopback: $R" ;;
esac
# ...and the allowed port on the SAME address still works, which is what makes
# this a scoping proof rather than a proof that loopback is simply broken.
R=$(asomega "curl -sS -m 10 -o /dev/null -w 'HTTP %{http_code}' http://$PROXY/api/tags")
out "$ curl -m 10 http://$PROXY/api/tags -> $R   (same address, allowed port)"
case "$R" in HTTP\ 200*) ;; *) fail P10 "the allowed port stopped working: $R" ;; esac

# --------------------------------------------------------------------- P11
say "P11 /api/pull must be REFUSED, and nothing may be pulled"
# THE REASON THIS SANDBOX HAS A PROXY AT ALL. Before it, the single allowed
# destination was a full Ollama API, and /api/pull reaches the public registry
# through a process the fence does not see, because Ollama runs as uid 999 and
# the fence is keyed on uid 1001.
BEFORE=$(/usr/local/bin/ollama list | sort)
out "ollama list BEFORE:" "$(echo "$BEFORE" | tail -n +2 | awk '{print "      " $1}')"
R=$(asomega "curl -sS -m 10 -X POST http://$PROXY/api/pull -d '{\"name\":\"qwen3:1.7b\"}'")
out "$ curl -X POST http://$PROXY/api/pull -d '{\"name\":\"qwen3:1.7b\"}'" "$R"
case "$R" in
    SANDBOX-PROXY-REFUSED*) ;;
    *) fail P11 "the pull was not refused by the proxy: $R" ;;
esac
CODE=$(asomega "curl -sS -m 10 -o /dev/null -w '%{http_code}' -X POST http://$PROXY/api/pull -d '{\"name\":\"qwen3:1.7b\"}'")
out "HTTP status: $CODE"
[ "$CODE" = "403" ] || fail P11 "expected 403, got $CODE"
# THE REFUSAL STRING IS NOT THE PROOF. A proxy could print it and forward anyway.
# The model store being byte-identical is the proof.
AFTER=$(/usr/local/bin/ollama list | sort)
out "ollama list AFTER:" "$(echo "$AFTER" | tail -n +2 | awk '{print "      " $1}')"
if [ "$BEFORE" = "$AFTER" ]; then
    out "model store identical before and after: NOTHING WAS PULLED"
else
    fail P11 "THE MODEL STORE CHANGED — something was pulled despite the 403"
fi
out "proxy log:" "$(tail -2 "$PROXY_LOG")"

# --------------------------------------------------------------------- P12
say "P12 the real Ollama port must now be unreachable to omega"
R=$(asomega "curl -sS -m 5 http://$REAL_OLLAMA/api/tags")
out "$ curl -m 5 http://$REAL_OLLAMA/api/tags   (bypassing the proxy)" "$R"
case "$R" in
    *'"models"'*) fail P12 "omega reached Ollama DIRECTLY — the proxy can be bypassed" ;;
    *"Failed to connect"*|*"Connection refused"*|*"not permitted"*) ;;
    *) fail P12 "unexpected answer from the direct port: $R" ;;
esac
# ...and root still reaches it, so P12 proves the FENCE and not a dead Ollama.
RC=$(curl -sS -m 5 -o /dev/null -w 'HTTP %{http_code}' http://$REAL_OLLAMA/api/tags 2>&1)
out "$ (control, as ROOT) curl http://$REAL_OLLAMA/api/tags -> $RC"
case "$RC" in
    HTTP\ 200*) ;;
    *) fail P12-control "Ollama is not up, so P12 proves nothing: $RC" ;;
esac

# --------------------------------------------------------------------- P13
say "P13 the other store-changing endpoints must be REFUSED too"
# /api/pull is the loud one. These two change the store without fetching, and an
# allowlist that only remembered the famous endpoint would let them through.
for SPEC in "DELETE /api/delete" "POST /api/create" "POST /api/push" "POST /api/copy"; do
    M=${SPEC%% *}; PATHP=${SPEC#* }
    R=$(asomega "curl -sS -m 10 -X $M http://$PROXY$PATHP -d '{\"name\":\"x\"}'")
    C=$(asomega "curl -sS -m 10 -o /dev/null -w '%{http_code}' -X $M http://$PROXY$PATHP -d '{\"name\":\"x\"}'")
    out "$ curl -X $M http://$PROXY$PATHP -> $C" "$R"
    case "$R" in
        SANDBOX-PROXY-REFUSED*) ;;
        *) fail P13 "$M $PATHP was not refused: $R" ;;
    esac
    [ "$C" = "403" ] || fail P13 "$M $PATHP returned $C, not 403"
done
# And the traversal, because an allowlist compared against a raw string is not an
# allowlist. /api/generate/../pull is /api/pull after normalisation.
R=$(asomega "curl -sS -m 10 --path-as-is -X POST 'http://$PROXY/api/generate/../pull' -d '{\"name\":\"x\"}'")
out "$ curl --path-as-is -X POST http://$PROXY/api/generate/../pull" "$R"
case "$R" in
    SANDBOX-PROXY-REFUSED*) ;;
    *) fail P13 "the traversal was not refused: $R" ;;
esac

say "ALL THIRTEEN PROBES BEHAVED AS REQUIRED"
printf 'Each printed the line the system actually produced. Nothing above is a\n'
printf 'claim; every refusal is quoted from the process that refused.\n'
