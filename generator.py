```python
import logging
import csv
import os
from faker import Faker
from random import choice
from typing import List, Dict, Any, Optional
from api_client import ApiClient

class TeamGenerator:
    """Generates and registers realistic fake teams, with CSV persistence."""
    
    def __init__(self, api_client: ApiClient, affiliation_pool: List[str]):
        self.api = api_client
        self.faker = Faker()
        self.affiliation_pool = affiliation_pool
        if not affiliation_pool:
            self.affiliation_pool = [self.faker.company() for _ in range(10)]
        self.csv_file = "teams.csv"

    def generate_teams(self, count: int, cid: str) -> List[Dict[str, Any]]:
        """
        Generates N teams (or loads them from CSV) and registers them with DOMjudge.
        """
        logging.info(f"Preparing to provide {count} teams...")
        
        # 1. Load existing teams from CSV
        existing_teams = self._load_teams_from_csv()
        teams_to_use = []
        
        if len(existing_teams) >= count:
            logging.info(f"Found {len(existing_teams)} teams in {self.csv_file}. Using the first {count}.")
            teams_to_use = existing_teams[:count]
        else:
            logging.info(f"Found {len(existing_teams)} teams in CSV. Generating {count - len(existing_teams)} more.")
            teams_to_use = existing_teams[:]
            needed = count - len(existing_teams)
            
            # Generate new teams
            start_index = len(existing_teams)
            new_teams = self._create_new_team_data(needed, start_index)
            teams_to_use.extend(new_teams)
            
            # Save ALL teams back to CSV (append new ones)
            self._save_teams_to_csv(new_teams) # Append only new ones to avoid rewriting everything? Or rewrite all?
            # Actually, let's just append the new ones.
            
        # 2. Register teams in DOMjudge
        registered_teams = []
        for team_data in teams_to_use:
            # Register Team
            team_id = self._register_team(team_data)
            if not team_id:
                continue
                
            # Register User
            if not self._register_user(team_data, team_id):
                continue
            
            # Update the team_data with the real ID from DOMjudge if needed, 
            # but we mostly rely on our generated IDs matching.
            team_data['domjudge_id'] = team_id
            registered_teams.append(team_data)
            
        logging.info(f"Successfully processed {len(registered_teams)} teams.")
        return registered_teams

    def _create_new_team_data(self, count: int, start_index: int) -> List[Dict[str, Any]]:
        """Creates the data structures for new teams."""
        new_teams = []
        for i in range(count):
            idx = start_index + i
            team_string_id = f"team{idx+1:03d}" # e.g. team001
            team_int_id = idx + 1
            team_name = f"{self.faker.word().capitalize()} {self.faker.word().capitalize()}"
            user_fake_name = self.faker.name()
            affiliation_name = choice(self.affiliation_pool)
            
            team_obj = {
                "id": team_string_id,
                "icpc_id": team_string_id,
                "label": team_string_id,
                "teamid": team_int_id,
                "name": team_name,
                "display_name": team_name,
                "affiliation": affiliation_name,
                "group_id": "participants",
                "username": team_string_id,
                "user_fullname": user_fake_name,
                "password": "team_password" # Consider randomizing this
            }
            new_teams.append(team_obj)
        return new_teams

    def _load_teams_from_csv(self) -> List[Dict[str, Any]]:
        """Reads teams from the CSV file."""
        if not os.path.exists(self.csv_file):
            return []
        
        teams = []
        try:
            with open(self.csv_file, 'r', newline='') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # Convert teamid back to int
                    if 'teamid' in row:
                        row['teamid'] = int(row['teamid'])
                    teams.append(row)
        except Exception as e:
            logging.error(f"Error reading {self.csv_file}: {e}")
            return []
        return teams

    def _save_teams_to_csv(self, new_teams: List[Dict[str, Any]]):
        """Appends new teams to the CSV file."""
        file_exists = os.path.exists(self.csv_file)
        fieldnames = [
            "id", "icpc_id", "label", "teamid", "name", "display_name", 
            "affiliation", "group_id", "username", "user_fullname", "password"
        ]
        
        try:
            with open(self.csv_file, 'a', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
                if not file_exists:
                    writer.writeheader()
                writer.writerows(new_teams)
            logging.info(f"Saved {len(new_teams)} new teams to {self.csv_file}")
        except Exception as e:
            logging.error(f"Error writing to {self.csv_file}: {e}")

    def _register_team(self, team_data: Dict[str, Any]) -> Optional[str]:
        """Registers the team with DOMjudge, checking for existence."""
        
        # Check if team exists? 
        # The API client create_team might fail if it exists.
        # We can try to fetch it first or just try to create and handle error.
        # Let's try to create and handle the specific error or check if it exists.
        
        # Prepare API payload
        payload = {
            "id": team_data['id'],
            "icpc_id": team_data['icpc_id'],
            "label": team_data['label'],
            "name": team_data['name'],
            "display_name": team_data['display_name'],
            "affiliation": team_data['affiliation'],
            "group_id": team_data['group_id']
        }
        
        # Try to create
        result = self.api.create_team(payload)
        
        if result and 'id' in result:
            logging.info(f"Created team: {team_data['name']} (ID: {result['id']})")
            return result['id']
        
        # If creation failed, maybe it exists?
        # We can assume if it failed, it might be because of ID conflict.
        # Let's try to fetch it to confirm.
        # Note: DOMjudge API might return 409 or 500.
        
        # Ideally we would check if it exists first.
        # But we don't have a get_team(id) in api_client yet, only get_scoreboard/submissions.
        # Let's assume if create fails, we check if we can proceed.
        
        logging.warning(f"Could not create team {team_data['id']}. It might already exist.")
        return team_data['id'] # Return the ID anyway so we can try to link user

    def _register_user(self, team_data: Dict[str, Any], team_id: str) -> bool:
        """Registers the user for the team."""
        user_data = {
            "username": team_data['username'],
            "name": team_data['user_fullname'],
            "password": team_data['password'],
            "team_id": team_id,
            "roles": ["team"]
        }
        
        result = self.api.create_user(user_data)
        if result:
            logging.info(f"Created user '{team_data['username']}' for team {team_id}.")
            return True
        
        logging.warning(f"Could not create user '{team_data['username']}'. It might already exist.")
        return True # Assume success/existence
```