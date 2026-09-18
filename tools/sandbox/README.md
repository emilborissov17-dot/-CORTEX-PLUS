# tools/sandbox — the Omega sandbox in WSL2 Ubuntu 24.04

Built 18 September 2026. This file is the setup **as it was actually run**, in
order, so the sandbox can be rebuilt from an empty distro without guessing.
Every command here was executed; where something failed on the way, the failure
and the fix are kept rather than smoothed over, because the failure is the part
that costs the next person an hour.

The proof that it works is not this file. It is `check.sh`, which tries to break
each guard and prints the line the system answered with. Run it after any change:

```
powershell -ExecutionPolicy Bypass -File tools\sandbox_check.ps1
```

## What this sandbox is

The Omega agent (PeTTa-based, lives outside this repo at
`C:\Users\emilb\Desktop\AGI\OMEGA_EXPERIMENT`) runs inside WSL2 as an OS user
with no password, no sudo, one writable directory, and exactly one reachable
network destination.

| guard | how |
|---|---|
| own OS user, no credentials, no sudo | `useradd -m -s /bin/bash omega`, `passwd -l omega`, not in group `sudo` |
| no network except local Ollama | `fence.sh` — iptables OUTPUT, `-m owner --uid-owner omega`, ACCEPT only `127.0.0.1:11434` |
| read-only filesystem, one scratch | tree copied `root:root` 755/644; `/home/omega/scratch` `omega:omega` 700 |
| Windows tree unreachable | `/etc/wsl.conf` `[automount] options="metadata,umask=077"` |
| no shell skill, no file-write skill | `src/skills.pl` `shell/2` replaced by a loud refusal; the writers removed from `src/helper.py` |
| every turn recorded | `src/providers.py` `llmProviderChat` wrapped → `/home/omega/scratch/turns.jsonl` |

## Setup, in the order it was run

Everything is driven from Windows with:

```
wsl -d Ubuntu -u root -e bash -lc "<cmd>"
```

### 0. The endpoint, decided by measurement

There are **two** Ollama servers on this machine and they are not the same thing:

* Windows, `127.0.0.1:11434`, pid 7860 — holds `qwen2.5:3b`, `cortex-l1b-3b`,
  `qwen2.5:7b`, `nomic-embed-text`. **Loopback-only bind, so WSL cannot reach it**
  (`curl` to the default gateway `192.168.240.1:11434` exits 28, timeout).
* Inside Ubuntu, `127.0.0.1:11434`, a systemd unit `ollama.service` — this is
  what `curl http://localhost:11434/api/tags` answers from inside the distro.

The sandbox uses the **in-distro** one, so no Windows network setting changes and
nothing is exposed past WSL's own loopback. `qwen2.5:3b` was pulled into it:

```
ollama pull qwen2.5:3b
```

It is mostly CPU here — `ollama ps` reports `78%/22% CPU/GPU`, because the GPU
has ~520 MiB free of 4096 MiB while Windows holds the rest.

### 1. RAM, before anything else

The distro was capped at 3 GB by `%USERPROFILE%\.wslconfig`, and the first
`qwen2.5:3b` generate call was **OOM-killed**:

```
oom-kill:constraint=CONSTRAINT_NONE,...,task=ollama,pid=10198,uid=999
Out of memory: Killed process 10198 (ollama) total-vm:23467012kB
```

`memory=3GB` → `memory=6GB` in `.wslconfig` (backup at `.wslconfig.bak.2026-09-18`).

### 2. The user and the filesystem

```
useradd -m -s /bin/bash omega && passwd -l omega
cp -r /mnt/c/Users/emilb/Desktop/AGI/OMEGA_EXPERIMENT/PeTTa/. /home/omega/omega/
```

**Copy, not mount.** A mount would make the Windows tree writable from inside the
fence and would put the agent one symlink away from the repo.

CRLF must be normalised or nothing runs — the Windows checkout is CRLF and `sh`
answers with `run.sh: 8: Syntax error: end of file unexpected (expecting "then")`,
which reads like a broken script:

```
grep -rlIU $'\r' /home/omega/omega | xargs -r sed -i 's/\r$//'     # 530 files
```

Then ownership, modes, and the one writable place:

```
chown -R root:root /home/omega/omega
find /home/omega/omega -type d -exec chmod 755 {} +
find /home/omega/omega -type f -exec chmod 644 {} +
chmod 755 /home/omega/omega/run.sh /home/omega/omega/build.sh /home/omega/omega/test.sh
mkdir -p /home/omega/scratch && chown omega:omega /home/omega/scratch && chmod 700 /home/omega/scratch
```

### 3. SWI-Prolog

The distro shipped `swi-prolog-core` 9.0.4 only, which is a stub: `library(process)`,
`library(filesex)`, `library(uuid)` and `library(janus)` all fail to load and
`readutil` cannot open its shared object. PeTTa needs >= 9.3.x.

```
add-apt-repository -y ppa:swi-prolog/stable
apt-get install -y swi-prolog
```

This fails the first time:

```
trying to overwrite '/usr/lib/cmake/swipl/SWIPLConfig.cmake',
which is also in package swi-prolog-core 9.0.4+dfsg-3.1ubuntu4
```

The Ubuntu package conflicts with the PPA one. Remove it first, then repair:

```
dpkg --remove --force-depends swi-prolog-core
apt-get --fix-broken install -y
apt-get install -y swi-prolog          # 10.0.2-1-gb8d8f931a-nobleppa2
```

MORK and FAISS are **not** built. `run.sh` falls back to plain `swipl` when
`mork_ffi/target/release/libmork_ffi.so` is absent, and neither `cargo` nor
`cmake` is installed.

### 4. Startup must not need the network

`run.metta:2` and `lib_omega.metta` call `git-import!`. Reading
`lib/lib_import.pl:86-91`, **`git-import!` is already a no-op when the target
directory exists**:

```prolog
( exists_directory(LocalDir) -> true
                              ; clone_repo(GitPath, LocalDir), ... )
```

So no edit to `run.metta` is needed — the Omega import is already satisfied by
`repos/Omega`. Only `petta_lib_chromadb` was missing:

```
git clone --depth 1 https://github.com/patham9/petta_lib_chromadb.git \
    /home/omega/omega/repos/petta_lib_chromadb
```

### 5. Python

```
python3 -m venv --system-site-packages /home/omega/venv
/home/omega/venv/bin/pip install pyyaml openai py-landlock websockets ddgs chromadb janus-swi
```

`chromadb` is required at **import** time, not lazily:
`repos/petta_lib_chromadb/lib_chromadb.py` builds a `PersistentClient` at module
scope. `torch`, `transformers`, `sentence-transformers` and the `e5-large-v2`
model are deliberately **not** installed — nothing the probes exercise imports
them, and they are ~3 GB against a 6 GB VM.

The module is `py_landlock` (underscore); the distribution is `py-landlock`.

### 6. The fence

```
cp tools/sandbox/fence.sh /usr/local/sbin/omega-fence.sh
sed -i 's/\r$//' /usr/local/sbin/omega-fence.sh && chmod 755 /usr/local/sbin/omega-fence.sh
/usr/local/sbin/omega-fence.sh
```

Persisted through `/etc/wsl.conf`, because iptables rules do not survive a
`wsl --shutdown`:

```ini
[boot]
systemd=true
command=/usr/local/sbin/omega-fence.sh

[user]
default=emilborissov

[automount]
options="metadata,umask=077"
```

`umask=077` is what puts `/mnt/c` out of omega's reach (probe P5). Both this and
the `.wslconfig` memory change need a restart, so there is exactly **one**:

```
wsl --shutdown        # never between 02:50 and 05:00 local
```

After it: `free -m` shows 5924 MB, `ollama.service` comes back with a new pid,
`openclaw-gateway` comes back on its own from the systemd **user** unit
`/home/emilborissov/.config/systemd/user/openclaw-gateway.service` (`Restart=always`;
it takes ~30 s to bind, so a check immediately after the restart sees nothing),
and the fence is reinstalled by `[boot] command`.

### 7. The skill fence

Three places had to change for `shell`, because each does a different job:

| file:line | what it does | change |
|---|---|---|
| `src/skills.pl:1` | the real `shell/2`, `process_create(path(timeout), ['-k','1s','5s','sh','-c',Cmd])` | body replaced by a refusal that names the fence. The predicate stays so `skills.metta:144`'s import resolves — an `existence_error` reads as a bug and invites a "fix" |
| `src/skills.metta:15` | the prompt line advertising `shell` to the model | replaced by one line stating the skills are absent, so a turn is not wasted retrying |
| `src/helper.py:28` | `STATIC_LLM_COMMANDS`, the parser allowlist that decides dispatch | `"shell"` removed |

The file writers (`write-file`, `write-file-b64`, `append-file`, `delete-file`)
were removed from `STATIC_LLM_COMMANDS` and from the prompt; `TWO_ARG_COMMANDS`
becomes empty because every two-argument command was a writer. `get-io-policy`
is **kept** — it reports the policy and writes nothing.

`profile/policy.yaml` was narrowed (original kept at `policy.yaml.orig`): read
`/home/omega/omega` and `/home/omega/venv`, read-write `/home/omega/scratch` and
`/dev/null`. `/tmp` is deliberately not writable.

### 8. Provider and turn log

`config/config.yaml` (original at `config.yaml.orig`):

```yaml
provider: OpenAIAPI
commchannel: test
openaiapi_url: "http://127.0.0.1:11434/v1/"
openaiapi_model: "qwen2.5:3b"
chromaDbPath: "/home/omega/scratch/chroma_db"
memoryDirectory: "/home/omega/scratch/memory"
openClawEnabled: disabled
```

`127.0.0.1` is spelled out rather than `localhost`: the fence matches on address,
and a name resolving to `::1` would be refused with a message about the wrong thing.

The turn log wraps `src/providers.py` `llmProviderChat` — the single choke point
every provider reaches (`registerLLMProvider` → `llmProviderStart` → this). One
JSON line per turn to `/home/omega/scratch/turns.jsonl` with `ts, provider, model,
prompt_chars, reply_chars, ms, reply`. Written in a `finally` block, so a call
that raised is still a turn.

## Rebuilding on a fresh distro

Run sections 1–8 in order. Section 6 must come after section 2 (the fence refuses
to install for a user that does not exist, rather than looking installed and
guarding nothing). Then `tools\sandbox_check.ps1` — ten probes, and any failure
stops the run and names itself.
