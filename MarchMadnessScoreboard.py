import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import matplotlib.pyplot as plt
import time
import json

# Load Google Sheets credentials from Streamlit Secrets
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

# Function to fetch team seeds from Google Sheets
@st.cache_data(ttl=300)
def get_team_seeds():
    """Fetch team seeds from Google Sheets."""
    seed_sheet = gc.open_by_url("https://docs.google.com/spreadsheets/d/1pQdTS-HiUcH_s40zcrT8yaJtOQZDTaNsnKka1s2hf7I/edit?gid=0#gid=0").worksheet('Team Seeds')
    data = seed_sheet.get_all_records()
    seeds = {row['Team']: row['Seed'] for row in data}
    return seeds

def get_live_results():
    """
    Fetch live game results from ESPN API, avoid duplicate counting,
    and skip first-four play-in games based on round information.
    """
    url = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard?tournament=ncaa"
    response = requests.get(url)
    data = response.json()
    
    # Initialize processed event IDs if not present
    if "processed_event_ids" not in st.session_state:
        st.session_state["processed_event_ids"] = set()
    
    # New results for games not yet processed
    new_games = {}
    new_losers = set()
    
    # Helper: Get team name with fallback
    def get_team_name(competitor):
        team = competitor.get("team", {})
        # Try to use the 'location' field (school name only)
        team_name = team.get("location", "").strip()
        if not team_name:
            # Fallback to displayName if location is empty
            team_name = team.get("displayName", "").strip()
        return team_name
    
    for event in data.get("events", []):
        event_id = event.get("id")
        if not event_id:
            continue
        
        # Skip already processed events
        if event_id in st.session_state["processed_event_ids"]:
            continue
        
        competitions = event.get("competitions", [])
        if not competitions:
            continue
        competition = competitions[0]
        
        # Check for round information to filter out first-four games.
        round_info = competition.get("round", {})
        round_name = ""
        if isinstance(round_info, dict):
            round_name = round_info.get("name", "").lower()
        # If round name indicates first-four (adjust as needed), skip this event.
        if "first four" in round_name:
            st.session_state["processed_event_ids"].add(event_id)
            continue
        
        competitors = competition.get("competitors", [])
        if len(competitors) < 2:
            continue
        
        team1_name = get_team_name(competitors[0])
        team2_name = get_team_name(competitors[1])
        
        try:
            score1 = int(competitors[0].get("score", "0"))
        except ValueError:
            score1 = 0
        try:
            score2 = int(competitors[1].get("score", "0"))
        except ValueError:
            score2 = 0
        
        # Determine winner (using the ESPN "winner" flag if available)
        if competitors[0].get("winner", False) or (score1 > score2):
            new_games[team1_name] = new_games.get(team1_name, 0) + 1
            new_losers.add(team2_name)
        elif competitors[1].get("winner", False) or (score2 > score1):
            new_games[team2_name] = new_games.get(team2_name, 0) + 1
            new_losers.add(team1_name)
        
        # Mark this event as processed
        st.session_state["processed_event_ids"].add(event_id)
    
    # Merge new results with cumulative results in session state
    if "all_results" not in st.session_state:
        st.session_state["all_results"] = {"games": new_games, "losers": new_losers}
    else:
        all_games = st.session_state["all_results"].get("games", {})
        all_losers = st.session_state["all_results"].get("losers", set())
        for team, wins in new_games.items():
            all_games[team] = all_games.get(team, 0) + wins
        all_losers = all_losers.union(new_losers)
        st.session_state["all_results"] = {"games": all_games, "losers": all_losers}
    
    return st.session_state["all_results"]["games"], st.session_state["all_results"]["losers"]


def get_all_espn_team_names():
    """
    Fetch all team names from ESPN API for the entire tournament.
    Returns a set of school names using the "location" field.
    """
    # Update the tournament_dates to match your tournament schedule (YYYYMMDD-YYYYMMDD)
    tournament_dates = "20250318-20250407"  
    url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard?tournament=ncaa&dates={tournament_dates}"
    response = requests.get(url)
    data = response.json()
    
    teams_set = set()
    for event in data.get("events", []):
        competitions = event.get("competitions", [])
        if not competitions:
            continue
        competition = competitions[0]
        competitors = competition.get("competitors", [])
        if len(competitors) < 2:
            continue
        # Use the "location" field to get just the school name
        team1 = competitors[0].get("team", {}).get("location", "").strip()
        team2 = competitors[1].get("team", {}).get("location", "").strip()
        if team1:
            teams_set.add(team1)
        if team2:
            teams_set.add(team2)
    return teams_set

# Function to cross-reference team names between ESPN API data and your Google Sheet
def cross_reference_team_names():
    """
    Compare team names from the full ESPN tournament data and your Google Sheet.
    Returns two sets:
      - Teams on ESPN but missing in your Google Sheet.
      - Teams in your Google Sheet but not on ESPN.
    """
    team_seeds = get_team_seeds()
    # Normalize Google Sheet names (lowercase, stripped of extra spaces)
    google_team_names = {team.strip().lower() for team in team_seeds.keys() if team.strip()}
    
    # Get all ESPN team names and normalize
    espn_team_names = {team.strip().lower() for team in get_all_espn_team_names()}
    
    teams_in_espn_not_in_google = espn_team_names - google_team_names
    teams_in_google_not_in_espn = google_team_names - espn_team_names
    
    return teams_in_espn_not_in_google, teams_in_google_not_in_espn

# Streamlit app setup
st.set_page_config(layout="wide")  # Expands layout to utilize more space
st.title("🏀 Guttman Madness Scoreboard 🏆")
st.write("Scores update automatically every minute. Each win gives points equal to the team's seed.")

# Initialize session state for tracking refresh time
if 'last_updated' not in st.session_state:
    st.session_state['last_updated'] = time.time()

# Function to update and display the scoreboard
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
            # Display the seed as a simple number in parentheses
            seed = team_seeds.get(team, 'N/A')
            try:
                seed_val = int(seed)
            except Exception:
                seed_val = 0
            wins = live_results.get(team, 0)
            current_points = wins * seed_val
            current_score += current_points
            
            # Calculate potential additional points only if the team is still in play.
            if team in losers:
                potential_points = 0
            else:
                potential_points = seed_val * (max_wins - wins)
            potential_remaining += potential_points
            
            # Format team display: strike-through if eliminated.
            if team in losers:
                teams_with_seeds.append(f"<s style='color:red'><strike>{team}</strike></s> ({seed})")
            else:
                teams_with_seeds.append(f"{team} ({seed})")
        
        max_possible = current_score + potential_remaining
        score_display = f"{current_score}/{max_possible}"
        teams_with_seeds_str = "\n".join(teams_with_seeds)
        scores.append([participant, current_score, max_possible, score_display, teams_with_seeds_str])
    
    df = pd.DataFrame(scores, columns=["Participant", "Current Score", "Max Score", "Score", "Teams (Seeds)"])
    
    # Compute ranking based solely on Current Score.
    df = df.sort_values(by="Current Score", ascending=False)
    df['Place'] = df['Current Score'].rank(method='min', ascending=False).astype(int)
    
    # Compute the potential remaining points.
    df['Remaining'] = df["Max Score"] - df["Current Score"]
    
    # Now, sort first by Place (which is based on Current Score) and then by Remaining (descending)
    df = df.sort_values(by=["Place", "Remaining"], ascending=[True, False])
    
    # Set Place as the index.
    df.set_index("Place", inplace=True)
    
    # Rename the score column to "Score/Potential"
    df.rename(columns={"Score": "Score/Potential"}, inplace=True)
    
    # Drop the temporary Remaining column so it's not displayed.
    df = df.drop(columns=["Remaining"])
    
    return df

def display_scoreboard():
    df = update_scores()
    
    # Create two columns for the table and the chart.
    col1, col2 = st.columns([3, 2])
    
    with col1:
        # Display only the selected columns in the table with the updated header.
        st.dataframe(df[["Participant", "Score/Potential", "Teams (Seeds)"]], height=600, use_container_width=True)
    
    with col2:
        # Create a horizontal bar chart with overlaying bars.
        fig, ax = plt.subplots(figsize=(6, 6))
        
        # Grey bar for the maximum (potential) score.
        ax.barh(df["Participant"], df["Max Score"], color='lightgrey')
        
        # Overlay the green bar for the current score.
        ax.barh(df["Participant"], df["Current Score"], color='green')
        
        ax.set_xlabel("Points")
        ax.set_title("March Madness PickX Progress")
        
        # Ensure the x-axis always starts at 0 and extends to the highest Max Score.
        max_val = df["Max Score"].max() if not df["Max Score"].empty else 1
        ax.set_xlim(0, max_val)
        
        # Invert y-axis so that the highest rank (Place 1) is at the top.
        ax.invert_yaxis()
        
        st.pyplot(fig)

if st.sidebar.checkbox("Show Cross-Reference Debug Info"):
    missing_espn, missing_google = cross_reference_team_names()
    st.write("### Cross-Reference Check")
    if missing_espn:
        st.write("Teams on ESPN but missing in Google Sheet:", list(missing_espn))
    if missing_google:
        st.write("Teams in Google Sheet but not on ESPN:", list(missing_google))
        st.write("ESPN teams:", list(get_all_espn_team_names()))
    if not missing_espn and not missing_google:
        st.write("All team names match!")

if st.sidebar.checkbox("Show Sample ESPN API Data"):
    url = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard?tournament=ncaa"
    response = requests.get(url)
    try:
        data = response.json()
        st.write("### Sample ESPN API Data")
        st.json(data)
    except Exception as e:
        st.write("Error fetching or parsing API data:", e)


# Display the scoreboard
display_scoreboard()

# Timer container at the bottom of the page
refresh_timer = st.empty()

# Auto-refreshing the dashboard without stacking
for i in range(60, 0, -1):
    refresh_timer.markdown(f"<p style='text-align:center; color:gray; font-size:12px; position:fixed; bottom:10px; left:0; right:0;'>🔄 Next refresh: <strong>{i} seconds</strong></p>", unsafe_allow_html=True)
    time.sleep(1)
    
st.session_state['last_updated'] = time.time()
st.rerun()

