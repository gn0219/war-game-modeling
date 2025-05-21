import json
from datetime import datetime
from typing import Dict, List, Any
from dataclasses import dataclass, asdict

@dataclass
class Event:
    timestamp: float
    event_type: str
    actor_id: str
    action: str
    target_id: str = None
    details: dict = None

    def to_dict(self):
        return {
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "actor_id": self.actor_id,
            "action": self.action,
            "target_id": self.target_id,
            "details": self.details
        }

@dataclass
class StateSnapshot:
    timestamp: float
    units: List[Dict]
    terrain_state: Dict
    combat_state: Dict

    def to_dict(self):
        return {
            "timestamp": self.timestamp,
            "units": self.units,
            "terrain_state": self.terrain_state,
            "combat_state": self.combat_state
        }

class SimulationLogger:
    def __init__(self, log_file: str):
        self.log_file = log_file
        self.events = []
        self.state_snapshots = []
        # 이벤트와 상태 스냅샷을 위한 별도의 파일 경로 생성
        self.events_file = log_file.replace('.json', '_events.json')
        self.snapshots_file = log_file.replace('.json', '_snapshots.json')

    def log_event(self, event: Event):
        """Log a single event"""
        self.events.append(event)
        
    def log_state(self, snapshot: StateSnapshot):
        """Log a state snapshot"""
        self.state_snapshots.append(snapshot)
        
    def save_logs(self):
        """Save all logs to file"""
        # 이벤트와 상태 스냅샷을 별도의 파일로 저장
        with open(self.events_file, 'w') as f:
            json.dump([e.to_dict() for e in self.events], f, indent=2)
        
        with open(self.snapshots_file, 'w') as f:
            json.dump([s.to_dict() for s in self.state_snapshots], f, indent=2)
            
    def get_events_by_type(self, event_type: str) -> List[Event]:
        """Get all events of a specific type"""
        return [event for event in self.events if event.event_type == event_type]
    
    def get_state_at_time(self, timestamp: float) -> StateSnapshot:
        """Get the state snapshot closest to the given timestamp"""
        return min(self.state_snapshots, key=lambda x: abs(x.timestamp - timestamp)) 