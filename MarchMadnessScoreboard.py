import streamlit as st
import pandas as pd
import requests
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import matplotlib.pyplot as plt
import time
import json

# -----------------------------
# Google Sheets Setup
# -----------------------------
try:
    credentials_dict = dict(st.secrets["google_service_account"])
    credentials = ServiceAccountCredentials.from_json_keyfile_dict(credentials_dict)
    gc = gspread.authorize(credentials)
    sheet = gc.open_by_url("https://docs.google.com/spreadsheets/d/1pQdTS-HiUcH_s40zcrT8yaJtOQZDTaNsnKka1s2hf7I/edit?gid=0#gid=0").sheet1
except Exception as e:
    st.error(f"⚠️ Error loading Google Sheets credentials: {e}")
    st.stop()

def get_participants():
    """Fetch participant picks from Google Sheets."""
    data = sheet.get_all_records()
    participants = {row['Participant']: [row['Team1'], row['Team2'], row['Team3'], row['Team4']] for row in data}
    return participants

@st.cache_data(ttl=300)
def get_team_seeds():
    """Fetch team seeds from Google Sheets."""
    seed_sheet = gc.open_by_url("https://docs.google.com/spreadsheets/d/1pQdTS-HiUcH_s40zcrT8yaJtOQZDTaNsnKka1s2hf7I/edit?gid=0#gid=0").worksheet('Team Seeds')
    data = seed_sheet.get_all_records()
    seeds = {row['Team']: row['Seed'] for row in data}
    return seeds

# -----------------------------
# NCAA API Functions using new endpoint structure
# -----------------------------
def get_team_name(comp):
    """
    Extract the team name from a competitor's dictionary.
    Prioritize the "short" field found under the "names" dictionary.
    Example competitor JSON:
      "names": {
         "char6": "CREIGH",
         "short": "Creighton",
         "seo": "creighton",
         "full": "Creighton University"
      }
    """
    names = comp.get("names", {})
    return names.get("short", "").strip()

def get_live_results():
    """
    Fetch game results from the NCAA API endpoint for men's college basketball (D1).
    Uses the endpoint: https://ncaa-api.henrygd.me/scoreboard/basketball-men/d1
    Returns:
      - games: a dictionary mapping team names (using the "short" field) to number of wins.
      - losers: a set of teams that lost at least one game.
    """
    url = "https://ncaa-api.henrygd.me/scoreboard/basketball-men/d1"
    response = requests.get(url)
    if response.status_code != 200:
        st.error(f"Scoreboard endpoint returned error code {response.status_code}. No live results available.")
        return {}, set()
    data = response.json()
    
    games = {}
    losers = set()
    games_list = data.get("games", [])
    
    for game_obj in games_list:
        # Each game object has an inner "game" dictionary.
        game = game_obj.get("game", {})
        home = game.get("home", {})
        away = game.get("away", {})
        home_team = get_team_name(home)
        away_team = get_team_name(away)
        
        try:
            home_score = int(home.get("score", 0))
        except:
            home_score = 0
        try:
            away_score = int(away.get("score", 0))
        except:
            away_score = 0

        if home_score > away_score:
            games[home_team] = games.get(home_team, 0) + 1
            losers.add(away_team)
        elif away_score > home_score:
            games[away_team] = games.get(away_team, 0) + 1
            losers.add(home_team)
    return games, losers

def get_all_ncaa_team_names():
    """
    Fetch all team names from the NCAA API endpoint.
    Returns a set of team names (using the "short" field) extracted from every game.
    """
    url = "https://ncaa-api.henrygd.me/scoreboard/basketball-men/d1"
    response = requests.get(url)
    if response.status_code != 200:
        st.error(f"Scoreboard endpoint returned error code {response.status_code} for team list.")
        return set()
    data = response.json()
    games_list = data.get("games", [])
    teams_set = set()
    for game_obj in games_list:
        game = game_obj.get("game", {})
        home = game.get("home", {})
        away = game.get("away", {})
        home_team = get_team_name(home)
        away_team = get_team_name(away)
        if home_team:
            teams_set.add(home_team)
        if away_team:
            teams_set.add(away_team)
    return teams_set

def cross_reference_team_names():
    """
    Compare team names from the NCAA API scoreboard and your Google Sheet.
    Returns two sets:
      - Teams on the NCAA API but missing in your Google Sheet.
      - Teams in your Google Sheet but not on the NCAA API.
    """
    team_seeds = get_team_seeds()
    google_team_names = {team.strip().lower() for team in team_seeds.keys() if team.strip()}
    ncaa_team_names = {team.strip().lower() for team in get_all_ncaa_team_names()}
    
    teams_in_api_not_in_sheet = ncaa_team_names - google_team_names
    teams_in_sheet_not_in_api = google_team_names - ncaa_team_names
    return teams_in_api_not_in_sheet, teams_in_sheet_not_in_api

# -----------------------------
# Streamlit App Display Functions
# -----------------------------
st.set_page_config(layout="wide")
st.title("🏀 Guttman Madness Scoreboard 🏆")
st.write("Scores update automatically every minute. Each win gives points equal to the team's seed.")

if 'last_updated' not in st.session_state:
    st.session_state['last_updated'] = time.time()

def update_scores():
    participants = get_participants()  # e.g., {"Alice": ["Creighton", "Louisville", "Duke", "Xavier"], ...}
    team_seeds = get_team_seeds()
    live_results, losers = get_live_results()
    max_wins = 6  # assuming each team can win up to 6 games
    
    rows = []
    for participant, teams in participants.items():
        current_score = 0
        potential_remaining = 0
        team_columns = []  # One column per team
        for team in teams:
            seed = team_seeds.get(team, 'N/A')
            try:
                seed_val = int(seed)
            except Exception:
                seed_val = 0
            wins = live_results.get(team, 0)
            current_points = wins * seed_val
            current_score += current_points
            
            if team in losers:
                potential_points = 0
            else:
                potential_points = seed_val * (max_wins - wins)
            potential_remaining += potential_points
            
            team_columns.append(f"{team} ({seed})")
        
        max_possible = current_score + potential_remaining
        score_display = f"{current_score}/{max_possible}"
        rows.append([participant, current_score, max_possible, score_display] + team_columns)
        
    df = pd.DataFrame(rows, columns=["Participant", "Current Score", "Max Score", "Score/Potential", "Team1", "Team2", "Team3", "Team4"])
    df = df.sort_values(by="Current Score", ascending=False)
    df['Place'] = df['Current Score'].rank(method='min', ascending=False).astype(int)
    df['Remaining'] = df["Max Score"] - df["Current Score"]
    df = df.sort_values(by=["Place", "Remaining"], ascending=[True, False])
    df.set_index("Place", inplace=True)
    df = df.drop(columns=["Remaining"])
    return df, losers

def style_team(cell_value, losers):
    """
    Returns a CSS style if the team (extracted from the cell text) is in the losers set.
    The cell_value is expected to be of the format "Team (seed)".
    """
    team = cell_value.split(" (")[0].strip().lower()
    if team in {t.lower() for t in losers}:
        return "text-decoration: line-through; color: red;"
    else:
        return ""

def display_scoreboard():
    df, losers = update_scores()
    # Determine which team columns exist
    expected_team_cols = ["Team1", "Team2", "Team3", "Team4"]
    team_cols = [col for col in expected_team_cols if col in df.columns]
    
    # Apply conditional styling using Pandas Styler
    styled_df = df.style.applymap(lambda cell: style_team(cell, losers), subset=team_cols)
    
    col1, col2 = st.columns([3, 2])
    with col1:
        st.write(styled_df)
    with col2:
        fig, ax = plt.subplots(figsize=(6, 6))
        ax.barh(df["Participant"], df["Max Score"], color='lightgrey')
        ax.barh(df["Participant"], df["Current Score"], color='green')
        ax.set_xlabel("Points")
        ax.set_title("March Madness PickX Progress")
        max_val = df["Max Score"].max() if not df["Max Score"].empty else 1
        ax.set_xlim(0, max_val)
        ax.invert_yaxis()
        st.pyplot(fig)

# -----------------------------
# Sidebar Debug Options
# -----------------------------
if st.sidebar.checkbox("Show Cross-Reference Debug Info"):
    missing_api, missing_sheet = cross_reference_team_names()
    st.write("### Cross-Reference Check")
    if missing_api:
        st.write("Teams on NCAA API but missing in Google Sheet:", list(missing_api))
    if missing_sheet:
        st.write("Teams in Google Sheet but not on NCAA API:", list(missing_sheet))
    if not missing_api and not missing_sheet:
        st.write("All team names match!")

if st.sidebar.checkbox("Show Sample NCAA API JSON Data"):
    url = "https://ncaa-api.henrygd.me/scoreboard/basketball-men/d1"
    response = requests.get(url)
    try:
        data = response.json()
        st.write("### Sample NCAA API JSON Data")
        st.json(data)
    except Exception as e:
        st.write("Error fetching or parsing NCAA API JSON data:", e)
        st.write("Raw response text:", response.text)

if st.sidebar.checkbox("Show NCAA API Team Names"):
    teams = get_all_ncaa_team_names()
    st.write("### NCAA API Team Names:")
    st.write(list(teams))

# -----------------------------
# Main Display & Auto-Refresh
# -----------------------------
display_scoreboard()

refresh_timer = st.empty()
for i in range(60, 0, -1):
    refresh_timer.markdown(
        f"<p style='text-align:center; color:gray; font-size:12px; position:fixed; bottom:10px; left:0; right:0;'>🔄 Next refresh: <strong>{i} seconds</strong></p>",
        unsafe_allow_html=True)
    time.sleep(1)
st.session_state['last_updated'] = time.time()
st.rerun()
