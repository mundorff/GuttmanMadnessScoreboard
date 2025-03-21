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
# NCAA API Functions
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
      - live_results: a dictionary mapping team names to today's wins.
      - losers_today: a set of teams that lost at least one game today.
    """
    url = "https://ncaa-api.henrygd.me/scoreboard/basketball-men/d1"
    response = requests.get(url)
    if response.status_code != 200:
        st.error(f"Scoreboard endpoint returned error code {response.status_code}. No live results available.")
        return {}, set()
    data = response.json()
    
    live_results = {}
    losers_today = set()
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
            live_results[home_team] = live_results.get(home_team, 0) + 1
            losers_today.add(away_team)
        elif away_score > home_score:
            live_results[away_team] = live_results.get(away_team, 0) + 1
            losers_today.add(home_team)
    return live_results, losers_today

# -----------------------------
# Helper: Load Previous Team-Level Data
# -----------------------------
def load_previous_team_data():
    """
    Scan the Google Sheet for worksheets named with a date (YYYY-MM-DD) that are before today
    and contain a "Team Details" column.
    Returns a dictionary mapping each participant to a dict of team-level data:
      { participant: { team: { "wins": cumulative_wins, "lost": bool } } }
    If no archive is found, returns an empty dictionary.
    """
    today_str = time.strftime("%Y-%m-%d")
    prev_date = None
    prev_sheet = None
    for ws in spreadsheet.worksheets():
        title = ws.title
        try:
            time.strptime(title, "%Y-%m-%d")
        except Exception:
            continue  # skip non-date worksheets
        if title < today_str:
            # Check if this worksheet has a "Team Details" column by reading its header
            records = ws.get_all_records()
            if records and "Team Details" in records[0]:
                if prev_date is None or title > prev_date:
                    prev_date = title
                    prev_sheet = ws
    team_data = {}
    if prev_sheet:
        records = prev_sheet.get_all_records()
        for row in records:
            participant = row.get("Participant")
            team_details_str = row.get("Team Details", "{}")
            try:
                team_details = json.loads(team_details_str)
            except Exception:
                team_details = {}
            team_data[participant] = team_details
    return team_data

# -----------------------------
# Archive Functionality (Archiving Team-Level Data)
# -----------------------------
def archive_scores(df, team_details_dict):
    """
    Archive the current scoreboard (DataFrame) along with team-level details to a new worksheet in the Google Sheet.
    The new worksheet will be named with today's date (e.g., "2025-03-20").
    If a worksheet for today already exists, it will be updated.
    """
    today_str = time.strftime("%Y-%m-%d")
    try:
        archive_sheet = spreadsheet.worksheet(today_str)
    except gspread.exceptions.WorksheetNotFound:
        rows = str(df.shape[0] + 10)
        cols = str(df.shape[1] + 5)
        archive_sheet = spreadsheet.add_worksheet(title=today_str, rows=rows, cols=cols)
    
    # Prepare data for archiving: include a new "Team Details" column.
    df_reset = df.reset_index()
    header = list(df_reset.columns) + ["Team Details"]
    data = [header]
    for _, row in df_reset.iterrows():
        participant = row["Participant"]
        # Get the JSON string for this participant; if not available, use "{}".
        team_details_json = team_details_dict.get(participant, "{}")
        data.append(list(row) + [team_details_json])
    
    archive_sheet.clear()
    archive_sheet.update("A1", data)
    st.success(f"Scoreboard archived to tab '{today_str}'!")

# -----------------------------
# Update Scores with Fixed Potential Max Calculation
# -----------------------------
def update_scores():
    """
    For each participant and team, load any archived team-level data (wins and lost status)
    from the most recent archive (if available) and update with today's results.
    
    For each team:
      - Total wins = (archived wins, default 0) + (today's wins)
      - If the team is lost (either archived lost flag or it lost today), its max is locked at (total wins * seed)
      - Otherwise, its max potential remains (seed * max_wins)
    
    Returns:
      - df: a DataFrame with participant-level cumulative current and max scores.
      - team_details_update: a dict mapping participant to a JSON string of updated team-level data.
    """
    participants = get_participants()
    team_seeds = get_team_seeds()
    live_results, losers_today = get_live_results()
    # Load archived team-level data (if any)
    prev_team_data = load_previous_team_data()  # {participant: {team: {"wins": x, "lost": bool}}}
    
    max_wins = 6  # maximum games per team
    results = {}         # participant-level totals for display
    team_details_update = {}  # updated team-level details per participant
    for participant, teams in participants.items():
        part_current = 0
        part_max = 0
        teams_display = []
        team_data_for_participant = {}
        for team in teams:
            seed = team_seeds.get(team, 'N/A')
            try:
                seed_val = int(seed)
            except Exception:
                seed_val = 0
            # Retrieve archived data for this team, if available; default to 0 wins and not lost.
            archived = prev_team_data.get(participant, {}).get(team, {"wins": 0, "lost": False})
            archived_wins = archived.get("wins", 0)
            archived_lost = archived.get("lost", False)
            todays_wins = live_results.get(team, 0)
            total_wins = archived_wins + todays_wins
            
            # A team is considered lost if it was marked lost previously or lost today.
            lost = archived_lost or (team in losers_today)
            current_points = total_wins * seed_val
            
            # If lost, the maximum potential is fixed to the current points.
            if lost:
                team_max = current_points
                teams_display.append(f"(L){team} ({seed})")
            else:
                team_max = seed_val * max_wins
                teams_display.append(f"{team} ({seed})")
            
            part_current += current_points
            part_max += team_max
            
            # Update team-level details for this participant.
            team_data_for_participant[team] = {"wins": total_wins, "lost": lost}
        results[participant] = {
            "current": part_current,
            "max": part_max,
            "teams_str": "\n".join(teams_display)
        }
        team_details_update[participant] = json.dumps(team_data_for_participant)
    
    # Build a DataFrame from participant-level results.
    rows = []
    for participant, data in results.items():
        score_display = f"{data['current']}/{data['max']}"
        rows.append([participant, data['current'], data['max'], score_display, data["teams_str"]])
    
    df = pd.DataFrame(rows, columns=["Participant", "Current Score", "Max Score", "Score/Potential", "Teams (Seeds)"])
    df = df.sort_values(by="Current Score", ascending=False)
    df['Place'] = df['Current Score'].rank(method='min', ascending=False).astype(int)
    df['Remaining'] = df["Max Score"] - df["Current Score"]
    df = df.sort_values(by=["Place", "Remaining"], ascending=[True, False])
    df.set_index("Place", inplace=True)
    df = df.drop(columns=["Remaining"])
    return df, team_details_update

def display_scoreboard():
    df, team_details_update = update_scores()
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
    return df, team_details_update

# -----------------------------
# Main Display, Auto-Archive & Auto-Refresh
# -----------------------------
st.set_page_config(layout="wide")
st.title("🏀 Guttman Madness Scoreboard 🏆")
st.write("Scores update automatically every minute. Each win gives points equal to the team's seed.")

if 'last_updated' not in st.session_state:
    st.session_state['last_updated'] = time.time()
if 'last_archived_date' not in st.session_state:
    st.session_state['last_archived_date'] = ""  # to track if today's archive has been done

df, team_details_update = display_scoreboard()

# --- Auto-Archive Logic ---
# Get current time (24-hour format) and current date.
current_time = time.strftime("%H:%M")
current_date = time.strftime("%Y-%m-%d")
# Check if it's 11:58 PM and if we haven't archived today.
if current_time == "23:58" and st.session_state.get("last_archived_date") != current_date:
    archive_scores(df, team_details_update)
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

