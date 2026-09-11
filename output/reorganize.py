"""One-time local reorganization helper; not part of the runtime."""
from pathlib import Path
import re

root = Path(__file__).resolve().parents[1]
package = root / 'talent_portal'
for path in package.rglob('*.py'):
    text = path.read_text(encoding='utf-8')
    for module in ('db', 'migrations', 'blueprints', 'services', 'jobs'):
        text = re.sub(r'\bfrom ' + module + r'(?=[ .])', 'from talent_portal.' + module, text)
    text = text.replace('from config import', 'from talent_portal.defaults import')
    text = text.replace('from app import require_admin', 'from talent_portal.application import require_admin')
    path.write_text(text, encoding='utf-8')

templates = package / 'templates'
mapping = {}
for path in list(templates.glob('*.html')):
    section = 'shared' if path.name == 'base.html' else ('admin' if path.name.startswith('admin') else 'candidate')
    target = templates / section / path.name
    target.parent.mkdir(exist_ok=True)
    mapping[path.name] = f'{section}/{path.name}'
    path.rename(target)

assets = package / 'static'
asset_map = {}
for path in list(assets.iterdir()):
    if not path.is_file():
        continue
    section = 'css' if path.suffix == '.css' else ('js' if path.suffix == '.js' else 'images/mainstreet')
    target = assets / section / path.name
    target.parent.mkdir(parents=True, exist_ok=True)
    asset_map[path.name] = f'{section}/{path.name}'
    path.rename(target)

for path in list(package.rglob('*.html')) + list(package.rglob('*.py')):
    if path.name == 'branding.py':
        continue
    text = path.read_text(encoding='utf-8')
    for old, new in mapping.items():
        text = text.replace(f'"{old}"', f'"{new}"').replace(f"'{old}'", f"'{new}'")
    for old, new in asset_map.items():
        text = text.replace(f"filename='{old}'", f"filename='{new}'")
    if path.suffix == '.html':
        text = text.replace("filename='images/mainstreet/logo.png'", 'filename=brand.logo')
        for old, new in [
            ('Mainstreet MMFB Interview Schedule', '{{ brand.name }} Interview Schedule'),
            ('Mainstreet MFB Recruitment Portal', '{{ brand.portal_title }}'),
            ('Mainstreet Recruitment Portal', '{{ brand.portal_title }}'),
            ('Mainstreet Microfinance Bank', '{{ brand.company_name }}'),
            ('Mainstreet MFB', '{{ brand.name }}'),
            ('MAINSTREET RECRUITMENT ADMIN PORTAL', '{{ brand.name }} · Hiring workspace'),
            ('MAINSTREET', '{{ brand.name }}'),
            ('recruitment@mainstreetmfb.com', '{{ brand.support_email }}'),
            ('Executive Trainee Program — 2026 Cohort', '{{ brand.program_name }}'),
            ('Executive Trainee Program', '{{ brand.program_name }}'),
            ('Executive Trainee Application', 'Your application'),
            ('the Executive Trainee recruitment program', '{{ brand.program_name }}'),
        ]:
            text = text.replace(old, new)
        text = text.replace("indexedDB.open('mainstreet-recruitment', 1)", 'indexedDB.open({{ brand.storage_key | tojson }}, 1)')
        # Move page-specific CSS to discoverable files; preserve JS/Jinja behavior.
        styles = re.findall(r'<style>(.*?)</style>', text, re.S)
        if styles and all('{{' not in s and '{%' not in s for s in styles):
            css_name = 'css/pages/' + path.stem + '.css'
            css_path = assets / css_name
            css_path.parent.mkdir(parents=True, exist_ok=True)
            css_path.write_text('\n'.join(styles).strip() + '\n', encoding='utf-8')
            text = re.sub(r'<style>.*?</style>', '', text, flags=re.S)
            text = text.replace('{% block extra_head %}', "{% block extra_head %}\n<link rel=\"stylesheet\" href=\"{{ url_for('static', filename='" + css_name + "') }}\">", 1)
    path.write_text(text, encoding='utf-8')
print('Imports, template paths, assets, and page styles reorganized.')
