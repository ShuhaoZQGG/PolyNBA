"""ESPN team ID mapping for NBA teams."""

# ESPN team abbreviation -> ESPN team ID
ESPN_TEAMS: dict[str, str] = {
    "ATL": "1",
    "BOS": "2",
    "NOP": "3",
    "CHI": "4",
    "CLE": "5",
    "DAL": "6",
    "DEN": "7",
    "DET": "8",
    "GSW": "9",
    "HOU": "10",
    "IND": "11",
    "LAC": "12",
    "LAL": "13",
    "MIA": "14",
    "MIL": "15",
    "MIN": "16",
    "BKN": "17",
    "NYK": "18",
    "ORL": "19",
    "PHI": "20",
    "PHX": "21",
    "POR": "22",
    "SAC": "23",
    "SAS": "24",
    "OKC": "25",
    "UTA": "26",
    "WAS": "27",
    "TOR": "28",
    "MEM": "29",
    "CHA": "30",
}

# Reverse map: ESPN ID -> abbreviation
ESPN_IDS: dict[str, str] = {v: k for k, v in ESPN_TEAMS.items()}

# Full name and city aliases for lookup
_ALIASES: dict[str, str] = {
    # Full names
    "hawks": "ATL",
    "celtics": "BOS",
    "pelicans": "NOP",
    "bulls": "CHI",
    "cavaliers": "CLE",
    "cavs": "CLE",
    "mavericks": "DAL",
    "mavs": "DAL",
    "nuggets": "DEN",
    "pistons": "DET",
    "warriors": "GSW",
    "rockets": "HOU",
    "pacers": "IND",
    "clippers": "LAC",
    "lakers": "LAL",
    "heat": "MIA",
    "bucks": "MIL",
    "timberwolves": "MIN",
    "wolves": "MIN",
    "nets": "BKN",
    "knicks": "NYK",
    "magic": "ORL",
    "76ers": "PHI",
    "sixers": "PHI",
    "suns": "PHX",
    "trail blazers": "POR",
    "blazers": "POR",
    "kings": "SAC",
    "spurs": "SAS",
    "thunder": "OKC",
    "jazz": "UTA",
    "wizards": "WAS",
    "raptors": "TOR",
    "grizzlies": "MEM",
    "hornets": "CHA",
    # City names
    "atlanta": "ATL",
    "boston": "BOS",
    "new orleans": "NOP",
    "chicago": "CHI",
    "cleveland": "CLE",
    "dallas": "DAL",
    "denver": "DEN",
    "detroit": "DET",
    "golden state": "GSW",
    "houston": "HOU",
    "indiana": "IND",
    "los angeles clippers": "LAC",
    "la clippers": "LAC",
    "los angeles lakers": "LAL",
    "la lakers": "LAL",
    "miami": "MIA",
    "milwaukee": "MIL",
    "minnesota": "MIN",
    "brooklyn": "BKN",
    "new york": "NYK",
    "orlando": "ORL",
    "philadelphia": "PHI",
    "phoenix": "PHX",
    "portland": "POR",
    "sacramento": "SAC",
    "san antonio": "SAS",
    "oklahoma city": "OKC",
    "utah": "UTA",
    "washington": "WAS",
    "toronto": "TOR",
    "memphis": "MEM",
    "charlotte": "CHA",
}

# Full team names for display
TEAM_NAMES: dict[str, str] = {
    "ATL": "Atlanta Hawks",
    "BOS": "Boston Celtics",
    "NOP": "New Orleans Pelicans",
    "CHI": "Chicago Bulls",
    "CLE": "Cleveland Cavaliers",
    "DAL": "Dallas Mavericks",
    "DEN": "Denver Nuggets",
    "DET": "Detroit Pistons",
    "GSW": "Golden State Warriors",
    "HOU": "Houston Rockets",
    "IND": "Indiana Pacers",
    "LAC": "LA Clippers",
    "LAL": "Los Angeles Lakers",
    "MIA": "Miami Heat",
    "MIL": "Milwaukee Bucks",
    "MIN": "Minnesota Timberwolves",
    "BKN": "Brooklyn Nets",
    "NYK": "New York Knicks",
    "ORL": "Orlando Magic",
    "PHI": "Philadelphia 76ers",
    "PHX": "Phoenix Suns",
    "POR": "Portland Trail Blazers",
    "SAC": "Sacramento Kings",
    "SAS": "San Antonio Spurs",
    "OKC": "Oklahoma City Thunder",
    "UTA": "Utah Jazz",
    "WAS": "Washington Wizards",
    "TOR": "Toronto Raptors",
    "MEM": "Memphis Grizzlies",
    "CHA": "Charlotte Hornets",
}


def lookup_team(query: str) -> tuple[str, str] | None:
    """Look up a team by abbreviation, full name, or city name.

    Args:
        query: Team abbreviation (e.g. "LAL"), name (e.g. "Lakers"),
               or city (e.g. "Los Angeles")

    Returns:
        (abbreviation, espn_id) tuple, or None if not found
    """
    q = query.strip().upper()

    # Direct abbreviation match
    if q in ESPN_TEAMS:
        return q, ESPN_TEAMS[q]

    # Alias match (case-insensitive)
    q_lower = query.strip().lower()
    if q_lower in _ALIASES:
        abbr = _ALIASES[q_lower]
        return abbr, ESPN_TEAMS[abbr]

    # Partial match on full team names
    for abbr, full_name in TEAM_NAMES.items():
        if q_lower in full_name.lower():
            return abbr, ESPN_TEAMS[abbr]

    return None
