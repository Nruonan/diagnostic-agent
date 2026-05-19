from app.agents.error_analysis import ErrorAnalysisAgent
from app.agents.planning import PlanningAgent
from app.agents.root_cause import RootCauseAgent
from app.agents.slow_sql import SlowSqlAgent
from app.config import Settings
from app.dashscope_client import DashScopeClient


class MainAgent:
    def __init__(self, settings: Settings):
        client = DashScopeClient(settings)
        self.planning = PlanningAgent(client, settings)
        self.error_analysis = ErrorAnalysisAgent(client, settings)
        self.slow_sql = SlowSqlAgent(client, settings)
        self.root_cause = RootCauseAgent(client, settings)

