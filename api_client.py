import requests
import logging
from requests.auth import HTTPBasicAuth
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from typing import Dict, Any, Optional

class ApiClient:
    """
    Handles all communication with the DOMjudge v4 REST API.
    Reads credentials from the main config dictionary.
    """
    def __init__(self, config: Dict[str, Any]):
        try:
            self.base_url = config['domjudge_url']
            user = config['admin_user']
            password = config['admin_pass']
        except KeyError as e:
            logging.error(f"Missing key {e} in config.json. Please check your config.")
            raise
            
        self.auth = HTTPBasicAuth(user, password)
        # self.session is the ADMIN session
        self.session = self._create_session()
        logging.info(f"API Client initialized for {self.base_url}")

    def _create_session(self) -> requests.Session:
        """Configures a request session with retries for robustness."""
        session = requests.Session()
        session.auth = self.auth
        
        retries = Retry(
            total=5,
            backoff_factor=1,
            status_forcelist=[500, 502, 503, 504]
        )
        adapter = HTTPAdapter(max_retries=retries)
        
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def _request(self, method: str, endpoint: str, **kwargs) -> Optional[Dict[str, Any]]:
        """
        Helper for making authenticated (as ADMIN) and error-handled API requests.
        DO NOT use for team submissions.
        """
        url = f"{self.base_url}/{endpoint}"
        try:
            # Uses self.session (admin auth)
            response = self.session.request(method, url, **kwargs)
            response.raise_for_status()

            if response.status_code == 204:
                return {"status": "success", "code": 204}

            if response.content:
                return response.json()
                
            return None
        except requests.exceptions.HTTPError as e:
            logging.error(f"HTTP Error: {e.response.status_code} for {method} {url}")
            logging.error(f"Response: {e.response.text}")
        except requests.exceptions.RequestException as e:
            logging.error(f"Request failed: {e} for {method} {url}")
        return None

    def get_contest(self, cid: str) -> Optional[Dict[str, Any]]:
        """Fetches contest details (as admin)."""
        return self._request("GET", f"contests/{cid}")

    def patch_contest(self, cid: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Patches contest details (as admin)."""
        payload = data.copy()
        payload['id'] = cid 
        return self._request("PATCH", f"contests/{cid}", data=payload)

    def get_problems(self, cid: str) -> Optional[list]:
        """Fetches all problems for a contest (as admin)."""
        return self._request("GET", f"contests/{cid}/problems")

    def create_team(self, team_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Creates a new team (as admin)."""
        return self._request("POST", "teams", json=team_data)

    def create_user(self, user_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Creates a new user (as admin)."""
        multipart_data = []
        for key, value in user_data.items():
            if isinstance(value, list):
                for item in value:
                    multipart_data.append((f"{key}[]", (None, item)))
            else:
                multipart_data.append((key, (None, str(value))))
        return self._request("POST", "users", files=multipart_data)

    def add_team_to_contest(self, team_id: str, cid: str) -> Optional[Dict[str, Any]]:
        """Attaches an existing team to a contest (as admin)."""
        payload = [team_id]
        return self._request("POST", f"contests/{cid}/teams", json=payload)

    # --- THIS IS THE CRITICAL FIX ---
    def submit_solution(self, cid: str, team_id: str, problem_id: str, lang_id: str, file_path: str, team_pass: str) -> Optional[Dict[str, Any]]:
        """
        Submits a solution file for a team, authenticating AS THAT TEAM.
        """
        endpoint = f"contests/{cid}/submissions"
        url = f"{self.base_url}/{endpoint}"
        
        # Authenticate as the team (team_id is the username), not the admin
        team_auth = HTTPBasicAuth(team_id, team_pass)

        # When a team submits for itself, it doesn't send 'team_id' in the body.
        # The server knows the team from the authentication.
        data = {
            'problem': problem_id,
            'language': lang_id,
        }
        
        try:
            with open(file_path, 'rb') as f:
                files = {'code': (file_path.split('/')[-1], f)}
                
                # We CANNOT use self._request here as it uses the admin session.
                # We must make a new, one-off request with team auth.
                # We create a temporary session with retries for robustness.
                
                session = requests.Session()
                session.auth = team_auth
                
                retries = Retry(total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
                adapter = HTTPAdapter(max_retries=retries)
                session.mount("http://", adapter)
                session.mount("https://", adapter)

                response = session.post(url, data=data, files=files)
                response.raise_for_status()
                
                if response.content:
                    return response.json()
                return None

        except requests.exceptions.HTTPError as e:
            logging.error(f"HTTP Error (Team {team_id}): {e.response.status_code} for {endpoint}")
            logging.error(f"Response (Team {team_id}): {e.response.text}")
        except requests.exceptions.RequestException as e:
            logging.error(f"Request failed (Team {team_id}): {e} for {endpoint}")
        except IOError as e:
            logging.error(f"Failed to read solution file {file_path}: {e}")
        
        return None

    def get_scoreboard(self, cid: str) -> Optional[Dict[str, Any]]:
        """Fetches the contest scoreboard (as admin)."""
        return self._request("GET", f"contests/{cid}/scoreboard")

    def get_submissions(self, cid: str) -> Optional[list]:
        """Fetches all submissions for the contest (as admin)."""
        return self._request("GET", f"contests/{cid}/submissions")

    def get_judgements(self, cid: str) -> Optional[list]:
        """Fetches all judgements for the contest (as admin)."""
        return self._request("GET", f"contests/{cid}/judgements")