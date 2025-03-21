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
    # Open the spreadsheet and get the primary sheet for participants.
    spreadsheet = gc.open_by_url("https://docs.google.com/spreadsheets/d/1pQdTS-HiUcH_s40zcrT8yaJtOQZDTaNsnKka1s2hf7I/edit?gid=0#gid=0")
    sheet = spreadsheet.sheet1
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
    seed_sheet = spreadsheet.worksheet('Team Seeds')
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
    """
    names = comp.get("names", {})
    return names.get("short", "").strip()

def get_live_results():
    """
    Fetch game results from the NCAA API endpoint for men's college basketball (D1).
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
# Archive Functionality
# -----------------------------
def archive_scores(df):
    """
    Archive the current scoreboard (DataFrame) to a new worksheet in the Google Sheet.
    The new worksheet will be named with today's date (e.g., "2025-03-20").
    If a worksheet for today already exists, it will be updated.
    """
    today_str = time.strftime("%Y-%m-%d")
    try:
        # Try to get an existing worksheet for today's date.
        archive_sheet = spreadsheet.worksheet(today_str)
    except gspread.exceptions.WorksheetNotFound:
        # Create a new worksheet if it doesn't exist.
        rows = str(df.shape[0] + 10)  # adding extra rows
        cols = str(df.shape[1] + 5)   # adding extra columns
        archive_sheet = spreadsheet.add_worksheet(title=today_str, rows=rows, cols=cols)
    
    # Prepare data for archiving (include the index as a column).
    data = [df.reset_index().columns.tolist()] + df.reset_index().values.tolist()
    archive_sheet.clear()  # clear previous data (if any)
    archive_sheet.update("A1", data)
    st.success(f"Scoreboard archived to tab '{today_str}'!")

def load_previous_cumulative_scores():
    """
    Scan the Google Sheet for worksheets named with a date (YYYY-MM-DD) that are before today.
    Returns two dictionaries:
      - cumulative: mapping each participant to a tuple (prev_current, prev_max).
      - prev_losers: mapping each participant to a set of teams that lost (extracted from the "Teams (Seeds)" column).
    If no previous archive is found, returns empty dictionaries.
    """
    today_str = time.strftime("%Y-%m-%d")
    prev_date = None
    prev_sheet = None
    # Loop through all worksheets in the spreadsheet
    for ws in spreadsheet.worksheets():
        title = ws.title
        # Check if the worksheet title is a date in YYYY-MM-DD format.
        try:
            time.strptime(title, "%Y-%m-%d")
        except Exception:
            continue  # skip non-date worksheets
        # Consider only archives from before today
        if title < today_str:
            if prev_date is None or title > prev_date:
                prev_date = title
                prev_sheet = ws
    cumulative = {}
    prev_losers = {}
    if prev_sheet:
        records = prev_sheet.get_all_records()
        for row in records:
            participant = row.get("Participant")
            try:
                prev_current = float(row.get("Current Score", 0))
            except:
                prev_current = 0
            try:
                prev_max = float(row.get("Max Score", 0))
            except:
                prev_max = 0
            # Parse the "Teams (Seeds)" column to get previously lost teams.
            teams_str = row.get("Teams (Seeds)", "")
            losers_set = set()
            for team_entry in teams_str.split("\n"):
                team_entry = team_entry.strip()
                if team_entry.startswith("(L)"):
                    # Remove the "(L)" marker and extract the team name (ignoring the seed).
                    team_name_with_seed = team_entry[3:].strip()
                    if " (" in team_name_with_seed:
                        team_name = team_name_with_seed.split(" (")[0]
                    else:
                        team_name = team_name_with_seed
                    losers_set.add(team_name)
            cumulative[participant] = (prev_current, prev_max)
            prev_losers[participant] = losers_set
    return cumulative, prev_losers

# -----------------------------
# Streamlit App Display Functions (with cumulative scores)
# -----------------------------
st.set_page_config(layout="wide")
st.title("🏀 Guttman Madness Scoreboard 🏆")
st.write("Scores update automatically every minute. Each win gives points equal to the team's seed.")

if 'last_updated' not in st.session_state:
    st.session_state['last_updated'] = time.time()
if 'last_archived_date' not in st.session_state:
    st.session_state['last_archived_date'] = ""  # to track if today's archive has been done

def update_scores():
    """
    Calculate today's scores from live results and add them to previous cumulative
    scores from the most recent archive (if available). Also, persist the lost status for teams
    that were marked lost in any previous archive.
    """
    participants = get_participants()
    team_seeds = get_team_seeds()
    live_results, losers = get_live_results()
    
    # Load previous cumulative scores and lost teams.
    prev_cum, prev_losers = load_previous_cumulative_scores()
    
    # Calculate today's scores for each participant.
    todays_results = {}
    max_wins = 6  # assuming each team can win up to 6 games
    for participant, teams in participants.items():
        todays_current = 0
        todays_max_possible = 0
        teams_with_seeds = []
        for team in teams:
            seed = team_seeds.get(team, 'N/A')
            try:
                seed_val = int(seed)
            except Exception:
                seed_val = 0
            wins = live_results.get(team, 0)
            current_points = wins * seed_val
            todays_current += current_points
            
            # Check if the team was marked lost previously.
            was_lost_before = team in prev_losers.get(participant, set())
            # Determine potential points: zero if the team lost either today or previously.
            if team in losers or was_lost_before:
                potential_points = 0
                todays_loss_today = True
            else:
                potential_points = seed_val * (max_wins - wins)
                todays_loss_today = False
            
            todays_max_possible += potential_points
            
            # Mark the team as lost if it lost previously or today.
            if was_lost_before or todays_loss_today:
                teams_with_seeds.append(f'(L){team} ({seed})')
            else:
                teams_with_seeds.append(f"{team} ({seed})")
                
        todays_results[participant] = {
            "todays_current": todays_current,
            "todays_max": todays_max_possible,
            "teams_str": "\n".join(teams_with_seeds)
        }
    
    # Build cumulative results by adding today's scores to the previous cumulative totals.
    rows = []
    for participant, data in todays_results.items():
        prev_current, prev_max = prev_cum.get(participant, (0, 0))
        cumulative_current = prev_current + data["todays_current"]
        cumulative_max = prev_max + data["todays_max"]
        score_display = f"{cumulative_current}/{cumulative_max}"
        rows.append([participant, cumulative_current, cumulative_max, score_display, data["teams_str"]])
    
    # Create and sort the DataFrame.
    df = pd.DataFrame(rows, columns=["Participant", "Current Score", "Max Score", "Score/Potential", "Teams (Seeds)"])
    df = df.sort_values(by="Current Score", ascending=False)
    df['Place'] = df['Current Score'].rank(method='min', ascending=False).astype(int)
    df['Remaining'] = df["Max Score"] - df["Current Score"]
    df = df.sort_values(by=["Place", "Remaining"], ascending=[True, False])
    df.set_index("Place", inplace=True)
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
        ax.set_title("March Madness PickX Progress (Cumulative)")
        max_val = df["Max Score"].max() if not df["Max Score"].empty else 1
        ax.set_xlim(0, max_val)
        ax.invert_yaxis()
        st.pyplot(fig)
    return df

# -----------------------------
# Main Display, Auto-Archive & Auto-Refresh
# -----------------------------
df = display_scoreboard()

# --- Auto-Archive Logic ---
# Get current time (24-hour format) and current date.
current_time = time.strftime("%H:%M")
current_date = time.strftime("%Y-%m-%d")
# Check if it's 11:58 PM and if we haven't archived today.
if current_time == "23:58" and st.session_state.get("last_archived_date") != current_date:
    archive_scores(df)
    st.session_state["last_archived_date"] = current_date

# Auto-refresh every 60 seconds.
refresh_timer = st.empty()
for i in range(60, 0, -1):
    refresh_timer.markdown(
        f"<p style='text-align:center; color:gray; font-size:12px; position:fixed; bottom:10px; left:0; right:0;'>🔄 Next refresh: <strong>{i} seconds</strong></p>",
        unsafe_allow_html=True)
    time.sleep(1)
st.session_state['last_updated'] = time.time()
st.rerun()
