"""Syntax-check every inline <script> in the pages (skipped when Node is not installed)."""
import glob, os, re, shutil, subprocess, tempfile, pytest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

@pytest.mark.skipif(shutil.which('node') is None, reason='node not installed')
@pytest.mark.parametrize('page', sorted(glob.glob(os.path.join(ROOT, '*.html'))))
def test_inline_scripts_parse(page):
    html = open(page, encoding='utf-8').read()
    for i, js in enumerate(re.findall(r'<script>(.*?)</script>', html, re.S)):
        with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False, encoding='utf-8') as f: f.write(js)
        r = subprocess.run(['node', '--check', f.name], capture_output=True, text=True)
        os.remove(f.name)
        assert r.returncode == 0, f'{os.path.basename(page)} script {i}: {r.stderr[:400]}'
