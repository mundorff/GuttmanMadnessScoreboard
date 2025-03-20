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
# ESPN Bracket Endpoint Functions
# -----------------------------
def get_live_results():
    """
    Fetch game results from the ESPN bracket endpoint for the 2025 tournament.
    Returns a dictionary mapping team name to wins and a set of teams that lost in any game.
    """
    url = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/bracket?season=2025"
    response = requests.get(url)
    data = response.json()
    
    games = {}
    losers = set()
    regions = data.get("regions", [])
    for region in regions:
        rounds = region.get("rounds", [])
        for rnd in rounds:
            matchups = rnd.get("matchups", [])
            for matchup in matchups:
                competitors = matchup.get("competitors", [])
                if len(competitors) < 2:
                    continue

                def get_team_name(comp):
                    team = comp.get("team", {})
                    # Use the 'location' field (school name) with fallback to 'displayName'
                    name = team.get("location", "").strip()
                    if not name:
                        name = team.get("displayName", "").strip()
                    return name

                team1_name = get_team_name(competitors[0])
                team2_name = get_team_name(competitors[1])
                
                try:
                    score1 = int(competitors[0].get("score", "0"))
                except:
                    score1 = 0
                try:
                    score2 = int(competitors[1].get("score", "0"))
                except:
                    score2 = 0

                # Determine the winner using the ESPN 'winner' flag if available
                if competitors[0].get("winner", False) or (score1 > score2):
                    games[team1_name] = games.get(team1_name, 0) + 1
                    losers.add(team2_name)
                elif competitors[1].get("winner", False) or (score2 > score1):
                    games[team2_name] = games.get(team2_name, 0) + 1
                    losers.add(team1_name)
    return games, losers

def get_all_espn_team_names():
    """
    Fetch all team names from the ESPN bracket endpoint for the full tournament.
    Returns a set of school names (using the 'location' field).
    """
    url = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/bracket?season=2025"
    response = requests.get(url)
    data = response.json()
    teams_set = set()
    regions = data.get("regions", [])
    for region in regions:
        rounds = region.get("rounds", [])
        for rnd in rounds:
            matchups = rnd.get("matchups", [])
            for matchup in matchups:
                competitors = matchup.get("competitors", [])
                if len(competitors) < 2:
                    continue
                team1 = competitors[0].get("team", {}).get("location", "").strip()
                team2 = competitors[1].get("team", {}).get("location", "").strip()
                if team1:
                    teams_set.add(team1)
                if team2:
                    teams_set.add(team2)
    return teams_set

def cross_reference_team_names():
    """
    Compare team names from the full ESPN bracket data and your Google Sheet.
    Returns two sets:
      - Teams on ESPN but missing in your Google Sheet.
      - Teams in your Google Sheet but not on ESPN.
    """
    team_seeds = get_team_seeds()
    # Normalize Google Sheet names (lowercase, stripped)
    google_team_names = {team.strip().lower() for team in team_seeds.keys() if team.strip()}
    # Normalize ESPN bracket team names
    espn_team_names = {team.strip().lower() for team in get_all_espn_team_names()}
    
    teams_in_espn_not_in_google = espn_team_names - google_team_names
    teams_in_google_not_in_espn = google_team_names - espn_team_names
    return teams_in_espn_not_in_google, teams_in_google_not_in_espn

# -----------------------------
# Streamlit App Display Functions
# -----------------------------
st.set_page_config(layout="wide")
st.title("🏀 Guttman Madness Scoreboard 🏆")
st.write("Scores update automatically every minute. Each win gives points equal to the team's seed.")

if 'last_updated' not in st.session_state:
    st.session_state['last_updated'] = time.time()

def update_scores():
    participants = get_participants()
    team_seeds = get_team_seeds()
    live_results, losers = get_live_results()
    
    scores = []
    max_wins = 6  # assuming each team can win up to 6 games
    for participant, teams in participants.items():
        current_score = 0
        potential_remaining = 0
        teams_with_seeds = []
        for team in teams:
            seed = team_seeds.get(team, 'N/A')
            try:
                seed_val = int(seed)
            except Exception:
                seed_val = 0
            wins = live_results.get(team, 0)
            current_points = wins * seed_val
            current_score += current_points
            
            # Calculate potential additional points if team hasn't been eliminated.
            if team in losers:
                potential_points = 0
            else:
                potential_points = seed_val * (max_wins - wins)
            potential_remaining += potential_points
            
            if team in losers:
                teams_with_seeds.append(f"<s style='color:red'><strike>{team}</strike></s> ({seed})")
            else:
                teams_with_seeds.append(f"{team} ({seed})")
        
        max_possible = current_score + potential_remaining
        score_display = f"{current_score}/{max_possible}"
        teams_with_seeds_str = "\n".join(teams_with_seeds)
        scores.append([participant, current_score, max_possible, score_display, teams_with_seeds_str])
    
    df = pd.DataFrame(scores, columns=["Participant", "Current Score", "Max Score", "Score", "Teams (Seeds)"])
    df = df.sort_values(by="Current Score", ascending=False)
    df['Place'] = df['Current Score'].rank(method='min', ascending=False).astype(int)
    df['Remaining'] = df["Max Score"] - df["Current Score"]
    df = df.sort_values(by=["Place", "Remaining"], ascending=[True, False])
    df.set_index("Place", inplace=True)
    df.rename(columns={"Score": "Score/Potential"}, inplace=True)
    df = df.drop(columns=["Remaining"])
    return df

def display_scoreboard():
    df = update_scores()
    col1, col2 = st.columns([3, 2])
    with col1:
        st.dataframe(df[["Participant", "Score/Potential", "Teams (Seeds)"]], height=600, use_container_width=True)
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
    missing_espn, missing_google = cross_reference_team_names()
    st.write("### Cross-Reference Check")
    if missing_espn:
        st.write("Teams on ESPN but missing in Google Sheet:", list(missing_espn))
    if missing_google:
        st.write("Teams in Google Sheet but not on ESPN:", list(missing_google))
    if not missing_espn and not missing_google:
        st.write("All team names match!")

if st.sidebar.checkbox("Show Sample ESPN Bracket Data"):
    url = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/bracket?season=2025"
    response = requests.get(url)
    try:
        data = response.json()
        st.write("### Sample ESPN Bracket JSON Data")
        st.json(data)
    except Exception as e:
        st.write("Error fetching or parsing bracket JSON data:", e)

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
