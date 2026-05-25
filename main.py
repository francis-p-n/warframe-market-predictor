import sys
import os

# Add src to the Python path so we can import the predictor module
sys.path.insert(0, os.path.abspath("src"))

from predictor.main import main

if __name__ == "__main__":
    main()
