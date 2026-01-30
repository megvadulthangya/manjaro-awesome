"""
Build state management
"""

import json
from datetime import datetime

class BuildState:
    """Manages build state persistence"""
    
    def __init__(self, state_file="build_state.json"):
        self.state_file = state_file
        self.state = self._load_state()
    
    def _load_state(self):
        """Load state from file"""
        try:
            with open(self.state_file, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            return {}
    
    def save_state(self):
        """Save state to file"""
        with open(self.state_file, 'w') as f:
            json.dump(self.state, f, indent=2)
    
    def set(self, key, value):
        """Set a state value"""
        self.state[key] = value
        self.state['last_updated'] = datetime.now().isoformat()
        self.save_state()
    
    def get(self, key, default=None):
        """Get a state value"""
        return self.state.get(key, default)
    
    def clear(self):
        """Clear all state"""
        self.state = {}
        self.save_state()