import json, pathlib

base = pathlib.Path(r'C:\Users\emilb\Desktop\AGI\CORTEX++_QWEN\memory\web_intelligence')
for f in sorted(base.rglob('*_web_intel.json')):
    try:
        d = json.loads(f.read_text(encoding='utf-8'))
        a = d.get('analysis', {})
        prob = a.get('problem', '')[:60] if a.get('problem') else 'НЯМА'
        sev = a.get('severity', 'НЯМА')
        size = f.stat().st_size
        print(f'{f.name[:45]:45} | {size:6}b | {sev:8} | {prob}')
    except Exception as e:
        print(f'{f.name[:45]:45} | ГРЕШКА: {e}')