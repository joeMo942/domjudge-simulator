# DOMjudge Contest Simulator

This project provides a complete simulation environment to automatically run a full ICPC-style contest on a DOMjudge instance using its REST API.

It generates fake teams, starts the contest, and simulates submissions based on realistic probabilities and timing. The entire simulation can be "fast-forwarded" using a time compression factor.

## Features

* **API-Driven:** Interacts directly with the DOMjudge v4 REST API.
* **Team Generation:** Automatically creates realistic fake teams with affiliations.
* **Realistic Submissions:** Uses a discrete event simulation engine.
    * Submission timing is randomized.
    * Number of submissions per team is based on a Poisson distribution.
    * Submission outcomes (Correct, WA, TLE, CE) are chosen based on configurable weights.
* **Time Compression:** Run a 5-hour contest in 5 minutes (or any factor you choose).
* **Reproducibility:** Use a fixed random seed to replicate a simulation run.
* **Freeze Handling:** Correctly logs the scoreboard freeze period.
* **Data Export:** Generates a final scoreboard (JSON) and a detailed submissions list (CSV).

## 1. Installation

1.  Clone this repository.
2.  Create a Python virtual environment:
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```
3.  Install the required dependencies:
    ```bash
    pip install -r requirements.txt
    ```

## 2. Configuration

Before running the simulation, you **must** set up two things:

### A. `config.json`

Create a `config.json` file in the project's root directory. You can copy the structure from the example below.

```json
{
  "domjudge_url": "[http://your-domjudge-instance.com/api/v4](http://your-domjudge-instance.com/api/v4)",
  "admin_user": "admin",
  "admin_pass": "your-admin-password",
  "contest_id": "c1",

  "team_generation": {
    "count": 50,
    "affiliation_pool": [
      "University of Atlantis",
      "Mars University",
      "Cyberdyne Institute of Technology"
    ]
  },

  "simulation_params": {
    "time_compression_factor": 60.0,
    "avg_subs_per_team": 8,
    "submission_weights": {
      "correct": 0.25,
      "wa": 0.50,
      "tle": 0.15,
      "ce": 0.10
    },
    "lang_map": {
      ".py": "py3",
      ".cpp": "cpp",
      ".java": "java"
    },
    "random_seed": 42,
    "contest_start_delay_sec": 15
  }
}
```

**Configuration Details:**

* `domjudge_url`: Full URL to your DOMjudge v4 API (e.g., `http://localhost/domjudge/api/v4`).
* `admin_user` / `admin_pass`: Credentials for a user with 'admin' or 'jury' role.
* `contest_id`: The **Contest ID (cid)** (e.g., 'c1', 'sample') of the contest you want to run. This contest *must* exist in DOMjudge.
* `team_generation.count`: Number of *new* fake teams to generate and add to the contest. Set to 0 to only use existing teams.
* `time_compression_factor`: How much to speed up time.
    * `1.0` = Real-time (a 5-hour contest takes 5 hours).
    * `60.0` = 60x speed (a 5-hour contest takes 5 minutes).
    * `300.0` = 300x speed (a 5-hour contest takes 1 minute).
* `avg_subs_per_team`: The average number of submissions a single team will make during the *entire* contest.
* `submission_weights`: The probability of choosing each submission type. Must sum to 1.0.
* `lang_map`: Maps file extensions from your `solutions/` dir to DOMjudge language IDs.
* `random_seed`: An integer for reproducible simulations.
* `contest_start_delay_sec`: Small delay to wait after patching the contest start time.

### B. `solutions/` Directory

You must provide the solution files for the simulator to use. The directory structure is **critical**:

```
solutions/
│
├── <problem_id_1>/
│   ├── correct.py
│   ├── wa.py
│   └── tle.py
│
└── <problem_id_2>/
    ├── correct.cpp
    ├── ce.cpp
    └── wa.java
```

* The first-level directory name (e.g., `problem_id_1`) **must** match the **Problem ID (ID)** in DOMjudge (e.g., 'sum', 'hello', or 'A').
* The file names **must** start with the outcome type: `correct`, `wa` (Wrong Answer), `tle` (Time Limit Exceeded), or `ce` (Compile Error).
* The file extension (e.g., `.py`, `.cpp`) must be present in your `lang_map` in `config.json`.

## 3. Running the Simulation

1.  Ensure your DOMjudge instance is running and accessible.
2.  Ensure the contest (`contest_id`) exists.
3.  Activate your virtual environment (`source venv/bin/activate`).
4.  Run the `main.py` script:

    ```bash
    python main.py
    ```

The script will:
1.  Log all actions to `simulation.log` and the console.
2.  Connect to the API and load problems.
3.  Generate and register new teams.
4.  Patch the contest to start **now**.
5.  Wait for the contest to go live.
6.  Schedule all submissions in a priority queue.
7.  Process the queue, making API calls at compressed-time intervals.
8.  Log when the freeze period begins.
9.  Wait for the (simulated) contest to end.
10. Fetch final results and save them to the `output/` directory.

## 4. Output

After a successful run, you will find two files in the `output/` directory:

* `scoreboard.json`: The complete final scoreboard in JSON format.
* `submissions.csv`: A CSV file listing every submission made, its timing, and its final verdict.