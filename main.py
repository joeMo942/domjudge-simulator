import json
import logging
import sys
from simulation import SimulationEngine

def setup_logging():
    """Configures logging to file and console."""
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] [%(levelname)s] - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.FileHandler("simulation.log"),
            logging.StreamHandler(sys.stdout)
        ]
    )

def load_config(path: str) -> dict:
    """Loads the JSON configuration file."""
    try:
        with open(path, 'r') as f:
            config = json.load(f)
        return config
    except FileNotFoundError:
        logging.error(f"Configuration file not found at {path}")
        sys.exit(1)
    except json.JSONDecodeError:
        logging.error(f"Failed to parse {path}. Please check for valid JSON.")
        sys.exit(1)

def main():
    """Main entry point for the simulator."""
    setup_logging()
    
    config_path = "config.json"
    
    logging.info(f"Loading configuration from {config_path}...")
    config = load_config(config_path)
    print(config)
    try:
        engine = SimulationEngine(config)
        engine.run()
    except Exception as e:
        logging.exception(f"An unhandled error occurred: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()