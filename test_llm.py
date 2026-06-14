import subprocess
r = subprocess.run(['ollama', 'run', 'qwen3:1.7b'], input=b'Return ONLY this JSON: {"test": true}', stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
print(repr(r.stdout.decode('utf-8', errors='ignore')[:500]))