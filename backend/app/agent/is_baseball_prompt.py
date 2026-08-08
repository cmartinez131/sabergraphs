"""
Decide if a prompt is about BASEBALL (MLB, players, stats, teams).

Usage:
    from ..agent.is_baseball_prompt import is_baseball_prompt
    if not is_baseball_prompt(text):
        # return graceful empty payload
"""

# High-signal baseball vocabulary (stats, nouns, leagues, teams).
BASEBALL_POSITIVE = {
    # leagues / org
    "mlb", "major league baseball", "world series", "american league", "national league", "al", "nl",
    # hitting stats / analytics
    "ops", "obp", "slg", "woba", "xba", "xslg", "xwoba", "xobp", "xiso", "iso", "babip",
    "k%", "k percent", "strikeout %", "bb%", "bb percent", "walk %", "whiff %", "chase rate",
    "barrel", "barrel rate", "hard-hit", "hard hit", "sweet spot", "exit velo", "exit velocity", "launch angle",
    "batting average", "avg", "slugging", "on-base", "isolated power",
    "rbi", "rbis", "home run", "home runs", "hr", "stolen bases", "steals", "sb", "total bases", "tb", "hbp",
    "plate appearances", "pa",
    "sprint speed", "statcast",
    # bat-tracking vocabulary (2024+ Statcast bat-tracking data)
    "bat speed", "swing length", "swing speed", "blast", "blasts", "blast rate",
    "squared up", "squared-up", "competitive swings", "fast swing", "swords", "whiff",
    # positions (concise)
    "1b", "2b", "3b", "ss", "rf", "lf", "cf", "c", "dh", "first base", "second base", "shortstop",
    # teams (common)
    "yankees", "mets", "red sox", "blue jays", "orioles", "rays",
    "dodgers", "giants", "padres", "rockies", "diamondbacks",
    "cubs", "cardinals", "pirates", "brewers", "reds",
    "braves", "phillies", "nationals", "marlins", "guardians",
    "white sox", "tigers", "twins", "royals",
    "astros", "mariners", "athletics", "rangers", "angels",
}

# Strong indicators of other sports or unrelated topics.
NEGATIVE_STRONG = {
    # other sports/leagues
    "nba", "basketball", "nfl", "football", "ncaa", "college football",
    "nhl", "hockey", "soccer", "premier league", "la liga", "serie a", "bundesliga",
    "cricket", "ipl", "rugby", "tennis", "golf", "formula 1", "f1", "motogp",
    
}

# Lower-signal baseball hints (require multiple hits).
SECONDARY_HINTS = {
    "batter", "hitter", "at bat", "at-bat", "lineup", "ballpark", "clubhouse", "triple", "double", "single"
}


def heuristic_is_baseball(text: str) -> bool | None:
    """
    Returns:
      True  -> looks like baseball
      False -> looks non-baseball
      None  -> unsure
    """
    padded = f" {' '.join((text or '').lower().split())} "

    # Strong negative: other sports or obviously unrelated topics.
    if any(f" {word} " in padded for word in NEGATIVE_STRONG):
        return False

    # Strong positive: MLB/stats/teams.
    if any(f" {word} " in padded for word in BASEBALL_POSITIVE):
        return True

    # Combo of secondary hints.
    secondary_hits = sum(1 for word in SECONDARY_HINTS if f" {word} " in padded)
    if secondary_hits >= 2:
        return True

    # Weak cue: year + stat-ish term.
    mentions_year = any(token.isdigit() and len(token) == 4 for token in padded.split())
    has_stat_phrase = any(phrase in padded for phrase in (
        " ops ", " obp ", " slg ", " woba ", " rbi ", " hr ", " stolen base ", " k% ", " bb% "
    ))
    if mentions_year and has_stat_phrase:
        return True

    return None


def is_baseball_prompt(text: str) -> bool:
    """
    Public entry: heuristic classifier. Returns False when unsure.
    """
    if not isinstance(text, str) or not text.strip():
        return False

    result = heuristic_is_baseball(text)
    return result if result is not None else False
