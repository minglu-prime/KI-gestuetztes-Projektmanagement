"""Check repository-relative Markdown links without accessing the network."""
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
files = [ROOT/'README.md', ROOT/'CONTRIBUTING.md', *sorted((ROOT/'docs').rglob('*.md'))]
errors, count = [], 0
for source in files:
    content = source.read_text(encoding='utf-8')
    # Ignore code examples; they are not rendered Markdown navigation.
    content = re.sub(r'```.*?```', '', content, flags=re.S)
    for link in re.findall(r'\[[^\]]*\]\(([^)]+)\)', content):
        link = link.strip().strip('<>')
        parsed = urlsplit(link)
        if parsed.scheme or link.startswith('#'):
            continue
        target = (source.parent / unquote(parsed.path)).resolve()
        if not target.is_relative_to(ROOT) or not target.exists():
            errors.append(f'{source.relative_to(ROOT)} -> {link}')
        count += 1
if errors:
    print('Broken local links:\n' + '\n'.join(errors))
    sys.exit(1)
print(f'OK: {count} local links in {len(files)} Markdown files.')
