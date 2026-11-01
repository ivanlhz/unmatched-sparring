"""Player-facing texts in several languages: Spanish (the default) and English.

Every text the human reads (panel buttons and labels, chat lines) is a tag looked up in the catalog of the language
the bot was launched with. The code only ever uses tags, never literal player-facing text:

    t("moves.stays", name=name)          # "{name} se queda donde esta." / "{name} stays where it is."
    tn("moves.squares", 3)               # plural: tags "moves.squares.one" / "moves.squares.other", `{n}` filled in
    plural(3, "noun.card")               # "3 cartas" / "3 cards"

A catalog is `data/i18n/<lang>.json`, a flat map tag -> `str.format` template. Adding a language is adding one more
file with the same tags: no code change. A tag missing in the chosen file falls back to `es.json` and, failing that,
to the tag itself: a text can be wrong, never a crash. Proper nouns (card titles, hero names, game terms printed in
English) are passed in as arguments and never translated.

The language is one process-wide setting (`set_language`, called by `play` from `language` in the configuration or
`--language`), because the chat helpers are module-level functions with no session to carry it."""
from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

DEFAULT = "es"
CATALOG_DIR = Path(__file__).resolve().parents[2] / "data" / "i18n"

_cache: dict[str, dict[str, str]] = {}
_current = DEFAULT


def available() -> tuple[str, ...]:
    """The languages with a catalog file, Spanish first."""
    found = sorted(p.stem for p in CATALOG_DIR.glob("*.json"))
    return tuple(sorted(found, key=lambda lang: lang != DEFAULT))


def catalog(lang: str) -> dict[str, str]:
    """The tag -> template map of `lang` ({} when its file is missing or unreadable)."""
    if lang not in _cache:
        try:
            data = json.loads((CATALOG_DIR / f"{lang}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        _cache[lang] = {k: v for k, v in data.items() if isinstance(v, str)} if isinstance(data, dict) else {}
    return _cache[lang]


def has(tag: str) -> bool:
    """Is `tag` in the catalog of the current language or in the Spanish one?"""
    return tag in catalog(_current) or tag in catalog(DEFAULT)


def set_language(lang: str | None) -> str:
    """Select the language; an unknown or empty one selects Spanish. Returns the one in force."""
    global _current
    _current = lang if isinstance(lang, str) and lang.isalpha() and catalog(lang) else DEFAULT
    return _current


def language() -> str:
    return _current


@contextmanager
def using(lang: str) -> Iterator[str]:
    """The language for the duration of a block (tests, one-off renders)."""
    before = _current
    try:
        yield set_language(lang)
    finally:
        set_language(before)


def t(tag: str, **kwargs) -> str:
    """The text for `tag` in the current language, `{placeholders}` filled from `kwargs`."""
    for lang in dict.fromkeys((_current, DEFAULT)):
        template = catalog(lang).get(tag)
        if template is None:
            continue
        try:
            return template.format(**kwargs)
        except (KeyError, IndexError, ValueError, AttributeError, TypeError):
            continue                       # a template that does not fit its arguments: try Spanish, then give up
    return tag


def tn(tag: str, n: int, **kwargs) -> str:
    """A plural text: `<tag>.one` when n == 1, else `<tag>.other`; `{n}` is available to the template."""
    return t(f"{tag}.{'one' if n == 1 else 'other'}", n=n, **kwargs)


def plural(n: int, noun: str) -> str:
    """'3 cartas' / '1 carta': `noun` is the tag of a `.one` / `.other` pair holding just the word."""
    return f"{n} {tn(noun, n)}"
