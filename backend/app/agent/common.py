# backend/app/agent/common.py
"""
Shared agent-layer infrastructure (audit S3 dedup).

One home for the pieces nl2sql.py and prompt.py used to define twice:
the Anthropic client factory, the stat alias vocabulary, the year
extractor, and the number formatter. Divergence between the two copies
was already a source of bugs — add here, not in the consumers.
"""
import os

# Anthropic SDK optional; both agent paths fall back to rule-based logic.
try:
    import anthropic  # type: ignore
except Exception:
    anthropic = None  # type: ignore

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")


def get_llm_client():
    """Anthropic client, or None when the SDK or key is absent."""
    if not ANTHROPIC_API_KEY or anthropic is None:
        return None
    try:
        return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Stat alias vocabulary: canonical column -> analyst phrases.
# prompt.py matches user text against these phrases (normalize_stat);
# nl2sql.py feeds the flat phrase->column view to the SQL planner prompt.
# ---------------------------------------------------------------------------
STAT_ALIASES = {
    'woba': ['woba', 'weighted on base average', 'weighted on-base average'],
    'xwoba': ['xwoba', 'expected woba', 'expected weighted on base'],
    'on_base_plus_slg': ['ops', 'on base plus slugging', 'on-base plus slugging'],
    'on_base_percent': ['obp', 'on base percentage', 'on-base percentage', 'on-base %'],
    'slg_percent': ['slg', 'slugging', 'slugging percentage'],
    'isolated_power': ['iso', 'isolated power'],
    'batting_avg': ['batting average', 'avg', 'ba'],
    'babip': ['babip', 'batting average on balls in play'],
    'wobacon': ['wobacon', 'woba on contact', 'woba on-contact'],
    'xwobacon': ['xwobacon', 'expected wobacon', 'x woba on contact'],
    'bacon': ['bacon', 'ba on contact', 'batting average on contact'],
    'xbacon': ['xbacon', 'expected ba on contact', 'x ba on contact'],
    'xba': ['xba', 'expected batting average', 'expected ba'],
    'xslg': ['xslg', 'expected slugging'],
    'xobp': ['xobp', 'expected obp', 'expected on base'],
    'xiso': ['xiso', 'expected iso', 'expected isolated power'],
    'home_run': ['hr', 'homers', 'home runs', 'homer'],
    'hit': ['hits', 'h'],
    'single': ['singles', '1b'],
    'double': ['doubles', '2b'],
    'triple': ['triples', '3b'],
    'strikeout': ['k', 'so', 'strikeouts'],
    'walk': ['bb', 'walks', 'base on balls'],
    'b_rbi': ['rbi', 'rbis', 'runs batted in'],
    'b_total_bases': ['tb', 'total bases'],
    'b_hit_by_pitch': ['hbp', 'hit by pitch'],
    'b_sac_fly': ['sf', 'sac fly', 'sacrifice fly'],
    'b_sac_bunt': ['sh', 'sac bunt', 'sacrifice bunt'],
    'b_gnd_into_dp': ['gidp', 'grounded into double play'],
    'b_gnd_into_tp': ['gitp', 'grounded into triple play'],
    'b_intent_walk': ['ibb', 'intentional walk'],
    'b_reached_on_error': ['roe', 'reached on error'],
    'b_total_pitches': ['pitches seen', 'total pitches'],
    'bb_percent': ['bb%', 'walk%', 'walk rate', 'bb pct', 'bb percentage', 'walk %'],
    'k_percent': ['k%', 'strikeout%', 'strikeout rate', 'k pct', 'k percentage', 'strikeout %', 'strike out percentage', 'k rate'],
    'whiff_percent': ['whiff%', 'whiff rate'],
    'swing_percent': ['swing%', 'swing rate'],
    'z_swing_percent': ['z-swing%', 'zone swing%', 'z swing rate'],
    'z_swing_miss_percent': ['z-whiff%', 'zone whiff%', 'z swing miss%'],
    'oz_swing_percent': ['o-swing%', 'chase rate', 'o swing%', 'chase%'],
    'oz_swing_miss_percent': ['o-whiff%', 'o swing miss%'],
    'oz_contact_percent': ['o-contact%', 'out of zone contact%'],
    'iz_contact_percent': ['z-contact%', 'zone contact%'],
    'f_strike_percent': ['first pitch strike%', 'first-pitch strike%'],
    'meatball_percent': ['meatball%', 'meatball rate'],
    'meatball_swing_percent': ['meatball swing%', 'meatball swing rate'],
    'hard_hit_percent': ['hard hit%', 'hard-hit%', 'hard hit rate'],
    'sweet_spot_percent': ['sweet spot%', 'sweet-spot%', 'sweet spot rate'],
    'barrel_batted_rate': ['barrel%', 'barrel rate'],
    'barrel': ['barrels'],
    'exit_velocity_avg': ['exit velocity', 'exit velo', 'avg exit velo', 'ev', 'avg exit velocity'],
    'launch_angle_avg': ['launch angle', 'avg launch angle', 'la'],
    'groundballs_percent': ['gb%', 'groundball%', 'ground ball rate'],
    'flyballs_percent': ['fb%', 'flyball%', 'fly ball rate'],
    'linedrives_percent': ['ld%', 'line drive%', 'line-drive rate'],
    'popups_percent': ['pu%', 'popup%', 'pop up rate'],
    'pull_percent': ['pull%', 'pull rate'],
    'opposite_percent': ['oppo%', 'opposite field%', 'opposite rate', 'opposite %'],
    'straightaway_percent': ['straightaway%', 'straightaway rate'],
    'in_zone': ['in-zone pitches', 'zone pitches'],
    'out_zone': ['out of zone pitches', 'o-zone pitches'],
    'edge_percent': ['edge%', 'edge rate'],
    'edge': ['edge pitches'],
    'pitch_count': ['pitches seen'],
    'pitch_count_fastball': ['fastballs seen', 'fastball seen'],
    'pitch_count_breaking': ['breaking seen', 'breaking balls seen'],
    'pitch_count_offspeed': ['offspeed seen'],
    'r_total_stolen_base': ['steal', 'steals', 'stolen base', 'stolen bases', 'sb'],
    'r_total_caught_stealing': ['caught stealing', 'cs'],
    'r_stolen_base_pct': ['sb%', 'stolen base%'],
    'r_total_pickoff': ['pickoffs'],
    'r_run': ['runs', 'r'],
    'sprint_speed': ['sprint speed', 'sprint ft/s', 'speed'],
    'n_bolts': ['bolts'],
    'hp_to_1b': ['home to first', 'home-to-first', 'htf'],
    'n_outs_above_average': ['oaa', 'outs above average'],
    'avg_swing_speed': ['swing speed'],
    'avg_swing_length': ['swing length', 'average swing length', 'avg swing length'],
    'fast_swing_rate': ['fast swing%', 'fast swing rate'],
    'squared_up_contact': ['squared-up contact', 'squared up contact%'],
    'squared_up_swing': ['squared-up swing', 'squared up swing%'],
    'primary_position': ['position'],
    # --- bat-tracking mart vocabulary (mart_bat_tracking_season /
    #     mart_batter_pitch_season; 2024+ bat-tracking era) ---
    'avg_bat_speed': ['bat speed', 'average bat speed', 'avg bat speed'],
    'blast_rate': ['blast rate', 'blasts', 'blast%', 'blast'],
    'squared_up_rate': ['squared up rate', 'squared-up rate', 'squared up%',
                        'squared up', 'squared-up'],
    'competitive_swings': ['competitive swings', 'competitive swing count'],
    'batter_run_value': ['batter run value', 'swing run value'],
    'swords': ['swords', 'sword count'],
}


def alias_to_canonical():
    """Flat {phrase: canonical_column} view of STAT_ALIASES (first canon wins)."""
    flat = {}
    for canon, phrases in STAT_ALIASES.items():
        for phrase in phrases:
            flat.setdefault(phrase, canon)
    return flat


def extract_years(text):
    """4-digit years (1900–2099) anywhere in `text`, in order of appearance.

    Character-scan rather than token split so embedded ranges like
    "2015-2025" or "2019to2023" are still found.
    """
    years_found, digits = [], ""
    for ch in str(text or ""):
        if ch.isdigit():
            digits += ch
        else:
            if len(digits) == 4:
                year_val = int(digits)
                if 1900 <= year_val <= 2099:
                    years_found.append(year_val)
            digits = ""
    if len(digits) == 4:
        year_val = int(digits)
        if 1900 <= year_val <= 2099:
            years_found.append(year_val)
    return years_found


def format_number_short(value):
    """Compact display formatting for narration (47, 12.3, 0.312)."""
    try:
        number = float(value)
    except Exception:
        return str(value)
    if abs(number) >= 100:
        return f"{number:.0f}"
    if abs(number) >= 10:
        return f"{number:.1f}"
    return f"{number:.3f}".rstrip("0").rstrip(".")
