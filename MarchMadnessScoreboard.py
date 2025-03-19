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
    participants = {row['Participant']: [row['Team1'], row['Team2'], row['Team3'], row['Team4']] for row in data if row['Participant'].strip()}
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
    for game in soup.find_all('div', class_='Scoreboard'):
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
st.set_page_config(layout="wide")
st.title("🏀 Guttman Madness Scoreboard 🏆")
st.write("Scores update automatically every minute. Each win gives points equal to the team's seed.")

# Function to update and display the scoreboard
def display_scoreboard():
    st.empty()  # Clears previous output before displaying the new scoreboard
    df = update_scores()
    df = df.dropna().reset_index(drop=True)
    
    col1, col2 = st.columns([3, 2])
    
    with col1:
        st.dataframe(df.set_index("Place"), height=600, use_container_width=True)
    
    with col2:
        fig, ax = plt.subplots(figsize=(6, 6))
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
    df = df.dropna().reset_index(drop=True)
    df = df.sort_values(by="Score", ascending=False)
    df["Place"] = df["Score"].rank(method="min", ascending=False).astype(int)
    df = df[["Place", "Participant", "Score", "Teams (Seeds)"]]
    
    return df

# Display the scoreboard
display_scoreboard()

# Auto-refreshing the dashboard without stacking
st.experimental_rerun()


