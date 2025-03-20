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

# Function to scrape live March Madness scores from CBS Sports
def get_live_results():
    """Fetch live game results from CBS Sports."""
    url = "https://www.cbssports.com/college-basketball/scoreboard/"
    response = requests.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')
    
    games = {}
    losers = set()
    for game in soup.find_all('div', class_='Scoreboard'):  # Example class name, adjust as needed
        teams = game.find_all('span', class_='TeamName')
        scores = game.find_all('span', class_='Score')
        
        if teams and scores:
            team1, team2 = teams[0].text.strip(), teams[1].text.strip()
            score1 = int(scores[0].text) if scores[0].text.isdigit() else 0
            score2 = int(scores[1].text) if scores[1].text.isdigit() else 0
            if score1 > score2:
                games[team1] = games.get(team1, 0) + 1
                losers.add(team2)
            else:
                games[team2] = games.get(team2, 0) + 1
                losers.add(team1)
    
    return games, losers

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
        
        st.pyplot(fig)

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

