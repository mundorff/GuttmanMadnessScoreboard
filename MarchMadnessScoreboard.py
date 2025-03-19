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
st.title("🏀 March Madness PickX Scoreboard 🏆")
st.write("Scores update automatically every minute. Each win gives points equal to the team's seed.")

# Initialize session state for tracking refresh time
if 'last_updated' not in st.session_state:
    st.session_state['last_updated'] = time.time()

# Function to update and display the scoreboard
def display_scoreboard():
    df = update_scores()
    
    # Create two columns for better spacing
    col1, col2 = st.columns([3, 2])
    
    with col1:
        st.dataframe(df, height=600, use_container_width=True)
    
    with col2:
        # Generate a bar chart
        fig, ax = plt.subplots(figsize=(6, 6))  # Adjust size to prevent cramping
        ax.barh(df["Participant"], df["Score"], color='royalblue')
        ax.set_xlabel("Score")
        ax.set_title("March Madness PickX Leaderboard")
        st.pyplot(fig)

# Function to update scores
def update_scores():
    participants = get_participants()
    team_seeds = get_team_seeds()
    live_results, losers = get_live_results()
    
    scores = []
    for participant, teams in participants.items():
        total_score = sum(live_results.get(team, 0) * team_seeds.get(team, 0) for team in teams)
        teams_with_seeds = "\n".join([f"<s style='color:red'><strike>{team}</strike></s> (Seed {team_seeds.get(team, 'N/A')})" if team in losers else f"{team} (Seed {team_seeds.get(team, 'N/A')})" for team in teams])
        scores.append([participant, total_score, teams_with_seeds])
    
    df = pd.DataFrame(scores, columns=["Participant", "Score", "Teams (Seeds)"])
    df = df.sort_values(by="Score", ascending=False)
    
    return df

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
