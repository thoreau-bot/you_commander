"""Tags and GitHub releases from the changelog. Run by .github/workflows/release.yml on every push to main;
also runs locally:  python tools/release.py --dry-run

For every "## x.y.z" heading in docs/CHANGELOG.md with no tag on the remote yet, it tags the commit that
introduced that heading (overrides in RELEASE_MAP for the early versions, whose headings were written
ahead of their last fix), builds a source zip, and creates a release with the changelog section as notes.
Identity: the workflow runs as github-actions[bot]."""
import os, re, subprocess, sys, json
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DRY = '--dry-run' in sys.argv
RELEASE_MAP = {'1.0.0': '29ad294', '1.1.0': '42ad6a2', '1.2.0': '0444edf', '1.3.0': '9dfa214', '1.4.0': 'decba3b',
               '1.5.0': '5802106', '1.6.0': 'ba97ee3', '1.7.0': 'e20232c', '1.8.0': 'c1797b2'}
def git(*a, **k): return subprocess.run(['git', *a], cwd=ROOT, check=True, capture_output=True, text=True, **k).stdout
def sh(*a): print('+', ' '.join(a)); return None if DRY else subprocess.run(a, cwd=ROOT, check=True)
cl = open(os.path.join(ROOT, 'docs', 'CHANGELOG.md'), encoding='utf-8').read()
sections = re.findall(r'^## (\d+\.\d+\.\d+)\n(.*?)(?=^## |\Z)', cl, re.S | re.M)
remote = set(re.findall(r'refs/tags/(v\d+\.\d+\.\d+)$', git('ls-remote', '--tags', 'origin'), re.M))
made = []
for ver, body in reversed(sections):            # oldest first, so "latest" ends on the newest
    tag = 'v' + ver
    if tag in remote: continue
    sha = RELEASE_MAP.get(ver) or (git('log', '--format=%H', '--diff-filter=AM', '-S', '## ' + ver, '--', 'docs/CHANGELOG.md').split() or [None])[-1]
    if not sha: print('no commit found for', ver); continue
    sha = git('rev-parse', sha).strip()
    notes = os.path.join(ROOT, f'release-notes-{ver}.md'); zipf = os.path.join(ROOT, f'youcommander-{ver}.zip')
    print(f'{tag} -> {sha[:7]}  ({len(body.strip())} chars of notes)')
    if DRY: continue
    open(notes, 'w', encoding='utf-8').write(body.strip() + '\n')
    sh('git', 'tag', '-a', tag, '-F', notes, sha)
    sh('git', 'archive', '--format=zip', f'--prefix=you_commander-{ver}/', '-o', zipf, tag)
    made.append((tag, ver, notes, zipf))
if made:
    sh('git', 'push', 'origin', *[t for t, *_ in made])
    for i, (tag, ver, notes, zipf) in enumerate(made):
        latest = 'true' if i == len(made) - 1 else 'false'
        sh('gh', 'release', 'create', tag, zipf, '--title', f'YouCommander {ver}', '--notes-file', notes, '--latest=' + latest)
print('nothing to do' if not made and not DRY else 'done')
