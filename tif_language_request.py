#!/usr/bin/env python3
"""
tif_language_request.py — Add a new language translation to the TIF sermon site.

Usage
─────
  # Translate current sermon only (this week):
  python tif_language_request.py --language "Korean" --mode once

  # Translate current sermon AND add to the weekly pipeline going forward:
  python tif_language_request.py --language "Korean" --mode ongoing

  # With requester info (for the commit message + email confirmation):
  python tif_language_request.py --language "Korean" --mode once \
    --name "John Kim" --email "john@example.com"

Requirements
────────────
  pip install anthropic --break-system-packages
  export ANTHROPIC_API_KEY="sk-ant-..."   (or set it in the CONFIG block below)
"""

import argparse
import urllib.request
import urllib.error
import json
import base64
import re
import sys
import os

try:
    import anthropic
except ImportError:
    print('ERROR: anthropic package not installed.')
    print('  Run: pip install anthropic --break-system-packages')
    sys.exit(1)

# ══════════════════════════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════════════════════════
GITHUB_TOKEN     = os.environ.get('GITHUB_TOKEN_PUSH') or os.environ.get('GITHUB_TOKEN') or ''
REPO             = 'toddblackhurst/tif-sermons'
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')   # or hardcode here
# ══════════════════════════════════════════════════════════════════════════════

BASE    = f'https://api.github.com/repos/{REPO}/contents/'
HEADERS = {
    'Authorization': f'Bearer {GITHUB_TOKEN}',
    'Accept': 'application/vnd.github.v3+json',
    'Content-Type': 'application/json',
}

# ── Language helpers ──────────────────────────────────────────────────────────

LANG_IDS = {
    'Japanese': 'ja', 'Korean': 'ko', 'Thai': 'th', 'Vietnamese': 'vi',
    'Filipino': 'tl', 'German': 'de', 'French': 'fr', 'Spanish': 'es',
    'Portuguese': 'pt', 'Hindi': 'hi', 'Malay': 'ms', 'Burmese': 'my',
    'Russian': 'ru', 'Arabic': 'ar', 'Dutch': 'nl', 'Italian': 'it',
    'Hebrew': 'he', 'Ukrainian': 'uk', 'Bengali': 'bn', 'Swahili': 'sw',
}

LANG_DISPLAY = {
    'Japanese': '日本語', 'Korean': '한국어', 'Thai': 'ภาษาไทย', 'Vietnamese': 'Tiếng Việt',
    'Filipino': 'Filipino', 'German': 'Deutsch', 'French': 'Français', 'Spanish': 'Español',
    'Portuguese': 'Português', 'Hindi': 'हिन्दी', 'Malay': 'Bahasa Melayu', 'Burmese': 'မြန်မာ',
    'Russian': 'Русский', 'Arabic': 'العربية', 'Dutch': 'Nederlands', 'Italian': 'Italiano',
    'Hebrew': 'עברית', 'Ukrainian': 'Українська', 'Bengali': 'বাংলা', 'Swahili': 'Kiswahili',
}

LANG_ALIASES = {
    'filipino / tagalog': 'Filipino',
    'tagalog / filipino': 'Filipino',
    'tagalog': 'Filipino',
    'filipino': 'Filipino',
}


def normalize_language(language: str) -> str:
    cleaned = re.sub(r'\s+', ' ', language.strip())
    return LANG_ALIASES.get(cleaned.lower(), cleaned.split(' / ')[0].split(' (')[0].strip())


def lang_id(language: str) -> str:
    return LANG_IDS.get(language, language.lower().replace(' ', '_').replace('/', '_'))


def lang_display(language: str) -> str:
    native = LANG_DISPLAY.get(language)
    if native == language:
        return language
    return f'{language} ({native})' if native else language


# ── GitHub API helpers ────────────────────────────────────────────────────────

def gh_get(path: str):
    if not GITHUB_TOKEN:
        raise RuntimeError('GitHub token required. Set GITHUB_TOKEN_PUSH or GITHUB_TOKEN.')
    req = urllib.request.Request(BASE + path, headers=HEADERS)
    resp = urllib.request.urlopen(req)
    data = json.loads(resp.read())
    content = base64.b64decode(data['content'].replace('\n', '')).decode('utf-8')
    return data['sha'], content


def gh_put(path: str, message: str, content_str: str, sha: str = None):
    if not GITHUB_TOKEN:
        raise RuntimeError('GitHub token required. Set GITHUB_TOKEN_PUSH or GITHUB_TOKEN.')
    encoded = base64.b64encode(content_str.encode('utf-8')).decode('ascii')
    body = {'message': message, 'content': encoded}
    if sha:
        body['sha'] = sha
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode('utf-8'),
        headers=HEADERS,
        method='PUT',
    )
    try:
        resp = urllib.request.urlopen(req)
        result = json.loads(resp.read())
        return True, result.get('commit', {}).get('sha', 'unknown')
    except urllib.error.HTTPError as e:
        return False, e.read().decode('utf-8')


# ── Translation via Claude ────────────────────────────────────────────────────

def translate_sermon(language: str, english_html: str, api_key: str) -> str:
    """
    Send the English article HTML to Claude and get back fully translated HTML.
    All tags are preserved; only text nodes are translated.
    """
    client = anthropic.Anthropic(api_key=api_key)

    prompt = f"""You are a skilled pastoral translator working for Taichung International Fellowship (TIF), \
an international church in Taiwan. Your task is to translate a sermon listening aid from English into {language}.

RULES — follow every one precisely:
1. Translate ALL visible text. Preserve ALL HTML tags exactly as written (tag names, class names, IDs, attributes).
2. Proper nouns:
   - Bible book names → use the standard {language} equivalent (e.g., "James" → "야고보서" in Korean)
   - Chapter:verse references (e.g., "2:1–13") → keep the numeric format exactly
   - Personal names (Zacchaeus, Todd Blackhurst) → transliterate naturally in {language}
3. Theological terms must be accurate and natural to {language}-speaking Christians.
4. Preserve all <em>, <strong>, <span class="flow-num">, <span class="kw-term"> tags with their content translated inside.
5. Section labels ("Big Idea", "Scripture", "Sermon Flow", "Key Words", "Anchor Statements", "Listening Cues", "Application Focus") → translate to the natural {language} equivalent.
6. Return ONLY the translated HTML. No preamble, no explanation, no markdown code fences.

ENGLISH HTML TO TRANSLATE:
{english_html}"""

    message = client.messages.create(
        model='claude-opus-4-5',
        max_tokens=8000,
        messages=[{'role': 'user', 'content': prompt}],
    )
    return message.content[0].text.strip()


# ── HTML manipulation ─────────────────────────────────────────────────────────

def extract_english_article(html: str) -> str:
    """Return the inner HTML of the English language content block."""
    _, _, inner = find_content_block(html, 'content-en')
    return inner


def find_content_block(html: str, element_id: str):
    """Return (start, end, inner_html) for a div/article block by id."""
    match = re.search(
        rf'<(?P<tag>article|div)\b[^>]*id=["\']{re.escape(element_id)}["\'][^>]*>',
        html,
        re.IGNORECASE,
    )
    if not match:
        raise ValueError(f'Could not find #{element_id} in index.html')

    tag = match.group('tag')
    token_re = re.compile(rf'</?{tag}\b[^>]*>', re.IGNORECASE)
    depth = 1
    for token in token_re.finditer(html, match.end()):
        if token.group(0).startswith('</'):
            depth -= 1
            if depth == 0:
                return match.start(), token.end(), html[match.end():token.start()]
        else:
            depth += 1

    raise ValueError(f'Could not find closing </{tag}> for #{element_id}')


def inject_language(html: str, language: str, lid: str, ldisplay: str, translated_inner: str) -> str:
    """
    1. Insert a language option into the current bottom-sheet language picker.
    2. Register the language in the LANGS object.
    3. Append a new content block before the footer.
    """
    if f'id="opt-{lid}"' not in html:
        option_html = (
            f'    <button class="lang-option" id="opt-{lid}" onclick="setLang(\'{lid}\')">\n'
            f'      <span class="lang-flag">🌐</span>\n'
            f'      <div><div class="lang-name">{language}</div><div class="lang-native">{ldisplay}</div></div>\n'
            f'      <span class="lang-check" id="check-{lid}" style="display:none">&#10003;</span>\n'
            f'    </button>\n'
        )
        html = re.sub(r'(\s*<hr class="sheet-divider">)', '\n' + option_html + r'\1', html, count=1)

    if f"'{lid}':" not in html:
        lang_entry = f"    '{lid}': {{ label: '{ldisplay}', flag: '🌐' }},\n"
        html = re.sub(r'(  const LANGS = \{\n)', r'\1' + lang_entry, html, count=1)

    content_html = (
        f'\n\n<!-- {language.upper()} -->\n'
        f'<div id="content-{lid}" class="lang-content" lang="{lid}">\n'
        f'{translated_inner}\n'
        f'</div>\n'
    )
    if f'id="content-{lid}"' in html:
        start, end, _ = find_content_block(html, f'content-{lid}')
        html = html[:start] + content_html.strip() + html[end:]
    else:
        html = re.sub(r'(\s*<footer class="footer">)', content_html + r'\1', html, count=1)
    return html


# ── Ongoing-mode config ───────────────────────────────────────────────────────

def update_languages_config(language: str, lid: str, ldisplay: str):
    """Add the language to languages_config.json so the weekly pipeline picks it up."""
    try:
        sha, content = gh_get('languages_config.json')
        config = json.loads(content)
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
        sha = None
        config = {'extra_languages': []}

    extras = config.setdefault('extra_languages', [])
    existing_ids = {lang.get('code') or lang.get('id') for lang in extras}
    if lid not in existing_ids:
        extras.append({'name': language, 'code': lid, 'display': ldisplay, 'active': True, 'ongoing': True})
        updated = json.dumps(config, indent=2, ensure_ascii=False) + '\n'
        ok, result = gh_put(
            'languages_config.json',
            f'Add {language} to ongoing sermon languages',
            updated,
            sha,
        )
        if not ok:
            raise RuntimeError(f'Failed to update languages_config.json: {result}')
        print(f'  Updated languages_config.json → added {language} ({lid})')
    else:
        print(f'  {language} already in languages_config.json — skipping config update')
    return config


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Add a new language translation to the TIF sermon site.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument('--language', required=True,
                        help='Language name, e.g. "Korean", "French", "Japanese"')
    parser.add_argument('--mode', choices=['once', 'ongoing', 'deny'], default='once',
                        help='"once" = current sermon only  |  "ongoing" = add to weekly pipeline  |  "deny" = no-op')
    parser.add_argument('--name',  default='', help='Requester full name (for commit message)')
    parser.add_argument('--email', default='', help='Requester email (for confirmation note)')
    parser.add_argument('--api-key', default='',
                        help='Anthropic API key (overrides ANTHROPIC_API_KEY env var)')
    parser.add_argument('--force', action='store_true',
                        help='Skip interactive prompts (used by GitHub Actions)')
    args = parser.parse_args()

    # Deny mode — nothing to do
    if args.mode == 'deny':
        print('Mode = deny — no translation will be created. Request ignored.')
        sys.exit(0)

    api_key = args.api_key or ANTHROPIC_API_KEY
    if not api_key:
        print('ERROR: Anthropic API key required.')
        print('  Set the ANTHROPIC_API_KEY environment variable, or pass --api-key "sk-ant-..."')
        sys.exit(1)

    language  = normalize_language(args.language)
    lid       = lang_id(language)
    ldisplay  = lang_display(language)
    requester = args.name or 'anonymous'

    print(f'╔══ TIF Language Request ══════════════════════════════')
    print(f'║  Language : {language}')
    print(f'║  Display  : {ldisplay}')
    print(f'║  Lang ID  : {lid}')
    print(f'║  Mode     : {args.mode}')
    print(f'║  Requester: {requester}')
    print(f'╚══════════════════════════════════════════════════════')

    # ── Step 1: Fetch index.html ───────────────────────────────────────────
    print('\n[1/5] Fetching index.html from GitHub…')
    idx_sha, idx_html = gh_get('index.html')
    print(f'      SHA: {idx_sha[:8]}…  ({len(idx_html):,} chars)')

    # ── Step 2: Check for duplicate ───────────────────────────────────────
    if f'id="content-{lid}"' in idx_html:
        print(f'\n⚠  Language "{language}" (id=content-{lid}) already exists in index.html.')
        if args.force:
            print('   --force flag set — overwriting.')
        else:
            resp = input('   Overwrite? (y/N): ').strip().lower()
            if resp != 'y':
                print('   Aborted.')
                sys.exit(0)

    # ── Step 3: Extract English content ───────────────────────────────────
    print('\n[2/5] Extracting English article HTML…')
    en_inner = extract_english_article(idx_html)
    print(f'      {len(en_inner):,} chars of English HTML extracted')

    # ── Step 4: Translate via Claude ──────────────────────────────────────
    print(f'\n[3/5] Generating {language} translation via Claude (20–45 sec)…')
    translated = translate_sermon(language, en_inner, api_key)
    print(f'      Translation complete: {len(translated):,} chars')

    # ── Step 5: Inject into HTML ──────────────────────────────────────────
    print('\n[4/5] Injecting translation into index.html…')
    updated_html = inject_language(idx_html, language, lid, ldisplay, translated)
    print(f'      HTML size: {len(idx_html):,} → {len(updated_html):,} chars')

    # ── Step 6: Push to GitHub ────────────────────────────────────────────
    commit_msg = f'Add {language} translation (requested by {requester})'
    print(f'\n[5/5] Pushing to GitHub…')
    print(f'      Commit: "{commit_msg}"')
    ok, result = gh_put('index.html', commit_msg, updated_html, idx_sha)
    if ok:
        print(f'      ✅ Pushed — commit {str(result)[:8]}')
        print(f'      🌐 Live at: https://toddblackhurst.github.io/tif-sermons/')
    else:
        print(f'      ❌ Push failed:\n{result}')
        sys.exit(1)

    # ── Step 7 (ongoing): Update pipeline config ───────────────────────────
    if args.mode == 'ongoing':
        print('\n[+] Updating languages_config.json for ongoing pipeline…')
        update_languages_config(language, lid, ldisplay)
        print('    ✅ Future sermons will automatically include this language.')
        print('    NOTE: Also update tif_push.py to call the translation step for this language.')

    print(f'\n✅ Done! {language} is now live on the TIF sermon page.')
    if args.email:
        print(f'   Consider sending a confirmation to {args.email}.')


if __name__ == '__main__':
    main()
