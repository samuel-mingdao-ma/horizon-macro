"""Create a portable, credential-free source archive for the research website."""
from pathlib import Path
import json
import zipfile
ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'public' / 'horizon-source.zip'
EXCLUDE = {'node_modules', '.git', 'dist', '.next', '.vinext', '.wrangler', '.sites-runtime', '__pycache__', '.venv', 'outputs', 'work', '.agents', '.codex'}
with zipfile.ZipFile(OUTPUT, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
    for path in sorted(ROOT.rglob('*')):
        rel = path.relative_to(ROOT)
        if not path.is_file() or any(part in EXCLUDE for part in rel.parts):
            continue
        if path == OUTPUT or path.suffix in {'.pyc', '.tsbuildinfo', '.pem'} or path.name.startswith(('.env', '.dev.vars')) or path.name == '.DS_Store':
            continue
        if str(rel) == '.openai/hosting.json':
            archive.writestr('horizon-macro/.openai/hosting.json', json.dumps({'d1': None, 'r2': None}, indent=2))
        else:
            archive.write(path, 'horizon-macro/' + str(rel))
print(f'Exported {OUTPUT.name} ({OUTPUT.stat().st_size:,} bytes)')
