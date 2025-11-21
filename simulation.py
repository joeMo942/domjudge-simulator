import os
import time
import json
import random
import heapq
import logging
import csv
import numpy as np
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional, Tuple
import pytz
from api_client import ApiClient
from generator import TeamGenerator

class SimulationEngine:
    """
    Runs the discrete event simulation for the DOMjudge contest.
    """
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.sim_config = config['simulation_params']
        self.cid = config['contest_id']
        
        # Seeding for reproducibility
        self.random_seed = self.sim_config['random_seed']
        random.seed(self.random_seed)
        
        # This is the ADMIN api client
        self.api = ApiClient(config)
        
        self.team_gen = TeamGenerator(
            self.api,
            config['team_generation']['affiliation_pool']
        )
        
        self.solution_map: Dict[str, Dict[str, List[str]]] = {}
        self.problems: List[Dict[str, Any]] = []
        self.teams: List[str] = [] # This will be a list of team IDs (strings)
        self.contest_data: Dict[str, Any] = {}
        
        # (sim_epoch_time, event_type, data)
        self.event_queue: List[Tuple[float, str, Any]] = []
        
        self.freeze_start_time: float = 0
        self.freeze_active: bool = False

    def run(self):
        """Main entry point to run the full simulation."""
        logging.info("===== STARTING DOMJUDGE SIMULATION =====")
        logging.info(f"Random seed set to: {self.random_seed}")
        
        if not self._prepare_simulation():
            logging.error("Simulation preparation failed. Aborting.")
            return

        self._schedule_submissions()
        self._process_event_queue()
        self._generate_reports()
        
        logging.info("===== SIMULATION FINISHED =====")

    def _prepare_simulation(self) -> bool:
        """Set up all prerequisites for the simulation."""
        logging.info("--- Preparing Simulation ---")
        
        # 1. Load solution files
        if not self._load_solutions():
            return False
            
        # 2. Fetch problems and teams
        if not self._fetch_contest_entities():
            return False

        # 3. Generate new teams if configured (or load from CSV)
        team_count = self.config['team_generation']['count']
        if team_count > 0:
            # This now handles CSV loading and generation
            generated_teams = self.team_gen.generate_teams(team_count, self.cid)
            
            # Extract just the IDs from the teams (using 'domjudge_id' or 'id')
            # The generator now ensures 'domjudge_id' is set if registered, or we fallback to 'id'
            new_team_ids = []
            for t in generated_teams:
                if 'domjudge_id' in t:
                    new_team_ids.append(t['domjudge_id'])
                elif 'id' in t:
                    new_team_ids.append(t['id'])
            
            self.teams.extend(new_team_ids)
        
        if not self.teams:
            logging.error("No teams found or generated. Cannot simulate.")
            return False
        
        logging.info(f"Total teams in simulation: {len(self.teams)}")

        # 4. Start the contest
        if not self._start_contest():
            return False
            
        logging.info("--- Preparation Complete ---")
        return True

    def _load_solutions(self) -> bool:
        """Scans the 'solutions/' directory and maps files to problems/outcomes."""
        logging.info("Loading solution files from 'solutions/'...")
        solution_dir = 'solutions'
        if not os.path.isdir(solution_dir):
            logging.error(f"Solution directory '{solution_dir}' not found.")
            return False
        
        for problem_code in os.listdir(solution_dir):
            problem_dir = os.path.join(solution_dir, problem_code)
            if os.path.isdir(problem_dir):
                self.solution_map[problem_code] = {}
                for f_name in os.listdir(problem_dir):
                    if f_name.startswith('.'): continue
                    
                    outcome = f_name.split('.')[0]
                    file_path = os.path.join(problem_dir, f_name)
                    
                    if outcome not in self.solution_map[problem_code]:
                        self.solution_map[problem_code][outcome] = []
                    self.solution_map[problem_code][outcome].append(file_path)
        
        if not self.solution_map:
            logging.error("No solution files found in 'solutions/' directory.")
            return False
            
        logging.info(f"Loaded solutions for {len(self.solution_map)} problems.")
        return True

    def _fetch_contest_entities(self) -> bool:
        """Get problem and team data from the API."""
        problems = self.api.get_problems(self.cid)
        if problems is None:
            logging.error("Failed to fetch problems.")
            return False
        
        # Filter problems to only those we have solutions for
        problem_ids_with_solutions = self.solution_map.keys()
        self.problems = [p for p in problems if p['id'] in problem_ids_with_solutions]
        
        if not self.problems:
            logging.error("No problems in contest match the solution file directories.")
            logging.error(f"Contest has problems: {[p['id'] for p in problems]}")
            logging.error(f"Solution dir has problems: {list(problem_ids_with_solutions)}")
            return False
            
        logging.info(f"Fetched {len(self.problems)} matching problems.")
        
        # We fetch teams *attached* to the contest
        scoreboard = self.api.get_scoreboard(self.cid)
        if scoreboard and 'rows' in scoreboard:
            self.teams = [row['team_id'] for row in scoreboard['rows']]
            logging.info(f"Fetched {len(self.teams)} existing teams.")
        
        return True

    def _start_contest(self) -> bool:
        """Patches the contest to start now and waits for it to be running."""
        
        custom_time_str = self.sim_config.get("custom_start_time")
        
        if custom_time_str:
            # --- New Logic: Parse the custom start time ---
            logging.info(f"Using custom start time: {custom_time_str}")
            try:
                time_part = custom_time_str[:-len(custom_time_str.split(" ")[-1])].strip()
                tz_part = custom_time_str.split(" ")[-1].strip()
                local_tz = pytz.timezone(tz_part)
                naive_dt = datetime.strptime(time_part, "%Y-%m-%d %H:%M:%S")
                aware_dt = local_tz.localize(naive_dt)
                start_iso = aware_dt.isoformat()
                logging.info(f"Converted custom time to ISO 8601: {start_iso}")

            except Exception as e:
                logging.error(f"Failed to parse 'custom_start_time': {e}")
                logging.error("Expected format: 'YYYY-MM-DD HH:MM:SS Timezone/Name'")
                return False
        
        else:
            # --- Original Logic: Start contest "now" ---
            logging.info("No custom start time found. Starting contest now...")
            delay = self.sim_config.get('contest_start_delay_sec', 15)
            start_dt = datetime.now(timezone.utc) + timedelta(seconds=delay)
            start_iso = start_dt.isoformat()
            logging.info(f"Set contest start time to {start_iso}. Waiting for contest to begin...")

        
        payload = {
            "start_time": start_iso,
            "force": "true"  # Send as string "true"
        }
        if not self.api.patch_contest(self.cid, payload):
            logging.error("Failed to patch contest start time.")
            return False
        
        # Poll until contest is active or starting soon
        parsed_start_time = datetime.fromisoformat(start_iso)
        
        # If the start time is more than ~10s in the future, don't poll
        if parsed_start_time > (datetime.now(parsed_start_time.tzinfo) + timedelta(seconds=10)):
             logging.info(f"Contest is scheduled to start at {start_iso}.")
             contest = self.api.get_contest(self.cid)
             if contest:
                 self.contest_data = contest
                 return True
             else:
                 logging.error("Failed to fetch contest data after setting start time.")
                 return False

        # If we are here, the start time is "now" or very soon, so we poll
        logging.info("Polling for contest to become active...")
        attempts = 0
        while attempts < 10:
            contest = self.api.get_contest(self.cid)
            if contest and contest.get('state') == 'running':
                self.contest_data = contest
                logging.info(f"Contest '{contest['name']}' is NOW RUNNING.")
                return True
            time.sleep(2)
            attempts += 1
            
        logging.error("Contest did not start. Check DOMjudge server.")
        return False

    def _schedule_submissions(self):
        """Populates the event queue with all submission events."""
        logging.info("--- Scheduling Submissions ---")
        
        start_str = self.contest_data['start_time']
        end_str = self.contest_data['end_time']
        freeze_str = self.contest_data.get('freeze_time')
        
        start_time = datetime.fromisoformat(start_str).timestamp()
        end_time = datetime.fromisoformat(end_str).timestamp()
        if freeze_str:
            self.freeze_start_time = datetime.fromisoformat(freeze_str).timestamp()
            
        duration_sec = end_time - start_time
        
        problem_ids = [p['id'] for p in self.problems]
        team_ids = self.teams
        weights = self.sim_config['submission_weights']
        
        total_submissions = 0
        for team_id in team_ids:
            # Use Poisson dist to find *how many* subs this team will make
            avg_subs = self.sim_config['avg_subs_per_team']
            num_subs = np.random.poisson(avg_subs)
            
            for _ in range(num_subs):
                # Use Uniform dist to find *when* they submit
                sim_time_offset = random.uniform(0, duration_sec)
                event_time = start_time + sim_time_offset
                
                # Choose *what* to submit
                prob_id = random.choice(problem_ids)
                outcome = random.choices(
                    list(weights.keys()), 
                    list(weights.values())
                )[0]
                
                # Get the file and lang for this submission
                submission_data = self._get_solution_file(prob_id, outcome)
                if submission_data:
                    file_path, lang_id = submission_data
                    
                    # --- THIS IS THE CRITICAL FIX ---
                    # Add the team's password to the event data
                    team_pass = "team_password" # This must match generator.py
                    data = (team_id, prob_id, lang_id, file_path, team_pass)
                    
                    heapq.heappush(self.event_queue, (event_time, "SUBMIT", data))
                    total_submissions += 1
        
        logging.info(f"Scheduled {total_submissions} submissions across {len(team_ids)} teams.")

    def _get_solution_file(self, prob_id: str, outcome: str) -> Optional[Tuple[str, str]]:
        """Finds a solution file for a given problem/outcome."""
        lang_map = self.sim_config['lang_map']
        
        if prob_id not in self.solution_map:
            logging.warning(f"No solutions found for problem {prob_id}")
            return None
        if outcome not in self.solution_map[prob_id]:
            # Try to fall back to 'wa' if the desired outcome is missing
            if 'wa' in self.solution_map[prob_id]:
                logging.warning(f"No '{outcome}' solution for {prob_id}, falling back to 'wa'.")
                outcome = 'wa'
            else:
                logging.warning(f"No '{outcome}' or 'wa' solution for {prob_id}")
                return None
            
        file_path = random.choice(self.solution_map[prob_id][outcome])
        file_ext = os.path.splitext(file_path)[1]
        
        if file_ext not in lang_map:
            logging.warning(f"Unknown language extension {file_ext} for {file_path}")
            return None
            
        lang_id = lang_map[file_ext]
        return file_path, lang_id

    def _process_event_queue(self):
        """Runs the simulation by processing the event queue with time compression."""
        logging.info("--- Processing Event Queue ---")
        
        if not self.event_queue:
            logging.warning("Event queue is empty. Nothing to simulate.")
            return

        compression = self.sim_config['time_compression_factor']
        if compression <= 0:
            logging.warning("Time compression factor must be > 0. Defaulting to 1.0 (real-time).")
            compression = 1.0

        sim_start_time = self.event_queue[0][0] # Time of first event
        real_start_time = time.time()
        
        end_time = datetime.fromisoformat(self.contest_data['end_time']).timestamp()

        logging.info(f"Time compression factor: {compression}x")
        
        while self.event_queue:
            event_sim_time, event_type, data = heapq.heappop(self.event_queue)
            
            # When should this event happen in *real* time?
            sim_time_elapsed = event_sim_time - sim_start_time
            real_time_elapsed = sim_time_elapsed / compression
            target_real_time = real_start_time + real_time_elapsed
            
            # Wait until it's time for this event
            wait_time = target_real_time - time.time()
            if wait_time > 0:
                time.sleep(wait_time)
            
            # Check for freeze period
            if self.freeze_start_time and not self.freeze_active:
                if event_sim_time >= self.freeze_start_time:
                    self.freeze_active = True
                    logging.info("--- SCOREBOARD IS NOW FROZEN ---")

            # Process the event
            dt_sim = datetime.fromtimestamp(event_sim_time).isoformat()
            if event_type == "SUBMIT":
                # --- THIS IS THE CRITICAL FIX ---
                # Unpack the team password
                team_id, prob_id, lang_id, file_path, team_pass = data
                logging.info(f"[SimTime: {dt_sim}] Team {team_id} submitting {prob_id}...")
                # Pass password to the new submit_solution method
                self.api.submit_solution(self.cid, team_id, prob_id, lang_id, file_path, team_pass)
        
        logging.info("--- Event Queue Empty ---")
        
        # Wait for judging to complete
        sim_end_time = end_time
        sim_time_elapsed = sim_end_time - sim_start_time
        real_time_elapsed = sim_time_elapsed / compression
        target_real_time = real_start_time + real_time_elapsed
        
        wait_time = target_real_time - time.time()
        if wait_time > 0:
            logging.info(f"Waiting {wait_time:.2f}s for simulated contest end...")
            time.sleep(wait_time)
        
        logging.info("Simulated contest duration has passed.")
        logging.info("Giving judges 10s (real time) to finish...")
        time.sleep(10)


    def _generate_reports(self):
        """Fetches final data and generates output CSV/JSON reports."""
        logging.info("--- Generating Final Reports ---")
        os.makedirs("output", exist_ok=True)
        
        # 1. Final Scoreboard
        scoreboard = self.api.get_scoreboard(self.cid)
        if scoreboard:
            path = "output/scoreboard.json"
            with open(path, 'w') as f:
                json.dump(scoreboard, f, indent=2)
            logging.info(f"Saved final scoreboard to {path}")
            
        # 2. Submissions CSV
        submissions = self.api.get_submissions(self.cid)
        if submissions:
            path = "output/submissions.csv"
            try:
                with open(path, 'w', newline='') as f:
                    if not submissions:
                        f.write("No submissions found.")
                        return
                        
                    # Get judgement results
                    judgements = self.api.get_judgements(self.cid)
                    judgement_map = {j['id']: j['verdict'] for j in judgements} if judgements else {}

                    fieldnames = ['id', 'team_id', 'problem_id', 'language_id', 'contest_time', 'verdict']
                    writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
                    writer.writeheader()
                    
                    for sub in submissions:
                        # Find the final judgement for this submission
                        final_judgement_id = sub.get('judgements', [None])[-1]
                        sub['verdict'] = judgement_map.get(final_judgement_id, 'pending')
                        writer.writerow(sub)
                        
                logging.info(f"Saved {len(submissions)} submissions to {path}")
            except Exception as e:
                logging.error(f"Failed to write submissions CSV: {e}")