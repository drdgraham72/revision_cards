"""
Question templates — deterministic rules for turning Factoid attributes
into question/answer pairs.

Each template is a callable that receives a Factoid and returns a
(question, answer, difficulty, template_id, tags) tuple, or None if
the Factoid doesn't have the required attributes.

Templates are registered per Topic. The engine runs all templates
for a Factoid's topic and collects the non-None results.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from models.domain import Topic, Difficulty, Factoid

# Type alias for a template function
TemplateResult = tuple[str, str, Difficulty, str, list[str]] | None
TemplateFn = Callable[[Factoid], TemplateResult]


@dataclass
class Template:
    id: str
    topic: Topic
    fn: TemplateFn


# ═══════════════════════════════════════════════════════════
# REGISTRY
# ═══════════════════════════════════════════════════════════
_TEMPLATES: list[Template] = []


def template(topic: Topic, template_id: str):
    """Decorator to register a question template."""
    def decorator(fn: TemplateFn) -> TemplateFn:
        _TEMPLATES.append(Template(id=template_id, topic=topic, fn=fn))
        return fn
    return decorator


def get_templates(topic: Topic) -> list[Template]:
    return [t for t in _TEMPLATES if t.topic == topic]


# ═══════════════════════════════════════════════════════════
# MOVIE TEMPLATES
# ═══════════════════════════════════════════════════════════

@template(Topic.MOVIES, "mov_director_year")
def _(f: Factoid) -> TemplateResult:
    if not f.has("director", "year"):
        return None
    return (
        f"Who directed the {f.attributes['year']} film '{f.entity_name}'?",
        f.attributes["director"],
        Difficulty.EASY,
        "mov_director_year",
        ["director"],
    )


@template(Topic.MOVIES, "mov_year_from_plot")
def _(f: Factoid) -> TemplateResult:
    if not f.has("plot", "year"):
        return None
    plot = f.attributes["plot"]
    # Use first ~80 chars of plot as a clue
    snippet = plot[:100].rsplit(" ", 1)[0] + "..."
    return (
        f"Which film's plot begins: \"{snippet}\"?",
        f"{f.entity_name} ({f.attributes['year']})",
        Difficulty.HARD,
        "mov_year_from_plot",
        ["plot", "identification"],
    )


@template(Topic.MOVIES, "mov_cast_film")
def _(f: Factoid) -> TemplateResult:
    cast = f.attributes.get("cast", [])
    if len(cast) < 2:
        return None
    return (
        f"Which film stars both {cast[0]} and {cast[1]}?",
        f"{f.entity_name} ({f.attributes.get('year', '?')})",
        Difficulty.MEDIUM,
        "mov_cast_film",
        ["cast", "identification"],
    )


@template(Topic.MOVIES, "mov_actor_director_collab")
def _(f: Factoid) -> TemplateResult:
    cast = f.attributes.get("cast", [])
    director = f.attributes.get("director")
    if not cast or not director:
        return None
    return (
        f"In which film did {cast[0]} work with director {director}?",
        f.entity_name,
        Difficulty.MEDIUM,
        "mov_actor_director_collab",
        ["cast", "director", "collaboration"],
    )


@template(Topic.MOVIES, "mov_genre_year_combo")
def _(f: Factoid) -> TemplateResult:
    genres = f.attributes.get("genre", [])
    if not genres or not f.has("year", "director"):
        return None
    genre_str = " / ".join(genres[:2])
    return (
        f"Name the {genre_str} film directed by {f.attributes['director']} in {f.attributes['year']}.",
        f.entity_name,
        Difficulty.MEDIUM,
        "mov_genre_year_combo",
        ["genre", "director", "year"],
    )


@template(Topic.MOVIES, "mov_rating_bracket")
def _(f: Factoid) -> TemplateResult:
    rating = f.attributes.get("imdb_rating")
    if not rating or not f.has("year"):
        return None
    bracket = "above 8" if rating >= 8 else "above 7" if rating >= 7 else "above 6"
    return (
        f"True or false: '{f.entity_name}' has an IMDb rating {bracket}?",
        f"True — it's rated {rating}",
        Difficulty.EASY,
        "mov_rating_bracket",
        ["rating", "true_false"],
    )


@template(Topic.MOVIES, "mov_box_office")
def _(f: Factoid) -> TemplateResult:
    bo = f.attributes.get("box_office")
    if not bo or bo == "N/A":
        return None
    return (
        f"Within $50 million, what was '{f.entity_name}' domestic box office?",
        bo,
        Difficulty.HARD,
        "mov_box_office",
        ["box_office", "estimation"],
    )


@template(Topic.MOVIES, "mov_runtime_game")
def _(f: Factoid) -> TemplateResult:
    runtime = f.attributes.get("runtime_min")
    if not runtime:
        return None
    over_under = "over" if runtime > 120 else "under"
    return (
        f"Is '{f.entity_name}' over or under 2 hours long?",
        f"It's {over_under} — {runtime} minutes",
        Difficulty.EASY,
        "mov_runtime_game",
        ["runtime", "over_under"],
    )


@template(Topic.MOVIES, "mov_awards")
def _(f: Factoid) -> TemplateResult:
    awards = f.attributes.get("awards")
    if not awards or "Oscar" not in awards:
        return None
    return (
        f"How many Oscar wins did '{f.entity_name}' receive?",
        awards,
        Difficulty.MEDIUM,
        "mov_awards",
        ["awards", "oscars"],
    )


@template(Topic.MOVIES, "mov_country_origin")
def _(f: Factoid) -> TemplateResult:
    country = f.attributes.get("country")
    if not country or country in ("USA", "United States", "N/A"):
        return None
    return (
        f"'{f.entity_name}' is a production from which country?",
        country,
        Difficulty.MEDIUM,
        "mov_country_origin",
        ["country", "origin"],
    )


# ═══════════════════════════════════════════════════════════
# MUSIC TEMPLATES
# ═══════════════════════════════════════════════════════════

@template(Topic.MUSIC, "mus_artist_album")
def _(f: Factoid) -> TemplateResult:
    artist = f.attributes.get("artist") or f.attributes.get("name")
    if not artist:
        return None
    return (
        f"Which artist released the album '{f.entity_name}'?",
        artist,
        Difficulty.EASY,
        "mus_artist_album",
        ["artist", "album"],
    )


@template(Topic.MUSIC, "mus_year_album")
def _(f: Factoid) -> TemplateResult:
    year = f.attributes.get("released") or f.attributes.get("year")
    if not year:
        return None
    return (
        f"In what year was the album '{f.entity_name}' released?",
        str(year),
        Difficulty.MEDIUM,
        "mus_year_album",
        ["year", "album"],
    )


@template(Topic.MUSIC, "mus_genre_clue")
def _(f: Factoid) -> TemplateResult:
    genre = f.attributes.get("genre")
    year = f.attributes.get("released") or f.attributes.get("year")
    if not genre or not year:
        return None
    return (
        f"Name the {genre} album released in {year} called '{f.entity_name}'.",
        f"{f.entity_name} by {f.attributes.get('artist', 'unknown')}",
        Difficulty.MEDIUM,
        "mus_genre_clue",
        ["genre", "year"],
    )


# ═══════════════════════════════════════════════════════════
# SCIENCE TEMPLATES (from Wikipedia extracts)
# ═══════════════════════════════════════════════════════════

@template(Topic.SCIENCE, "sci_what_is")
def _(f: Factoid) -> TemplateResult:
    extract = f.attributes.get("extract", "")
    if len(extract) < 50:
        return None
    # Use first sentence as the answer
    first_sentence = extract.split(".")[0] + "."
    if len(first_sentence) > 200:
        return None
    return (
        f"What is {f.entity_name}?",
        first_sentence,
        Difficulty.MEDIUM,
        "sci_what_is",
        ["definition"],
    )


@template(Topic.SCIENCE, "sci_true_false")
def _(f: Factoid) -> TemplateResult:
    extract = f.attributes.get("extract", "")
    if len(extract) < 100:
        return None
    return (
        f"True or false: {f.entity_name} — {extract[:120].rsplit(' ', 1)[0]}...",
        "True",
        Difficulty.MEDIUM,
        "sci_true_false",
        ["true_false"],
    )


# ═══════════════════════════════════════════════════════════
# GEOGRAPHY TEMPLATES
# ═══════════════════════════════════════════════════════════

@template(Topic.GEOGRAPHY, "geo_capital")
def _(f: Factoid) -> TemplateResult:
    capital = f.attributes.get("capital")
    if not capital:
        return None
    return (
        f"What is the capital of {f.entity_name}?",
        capital,
        Difficulty.EASY,
        "geo_capital",
        ["capital"],
    )


@template(Topic.GEOGRAPHY, "geo_extract_clue")
def _(f: Factoid) -> TemplateResult:
    extract = f.attributes.get("extract", "")
    if len(extract) < 80:
        return None
    snippet = extract[50:150].strip()
    if not snippet:
        return None
    return (
        f"Which place is described as: \"...{snippet}...\"?",
        f.entity_name,
        Difficulty.HARD,
        "geo_extract_clue",
        ["identification", "extract"],
    )
