"""
Write a ready-to-run demo simulation, with no Zep and no LLM.

It produces the same files /api/simulation/prepare would (agent profiles,
simulation_config.json, state.json), using MiroFish's own classes, for a
small fictional scenario: a university announces a tuition hike.
"""

import os
import sys

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app.config import Config  # noqa: E402
from app.services.oasis_profile_generator import OasisAgentProfile, OasisProfileGenerator  # noqa: E402
from app.services.simulation_config_generator import (  # noqa: E402
    AgentActivityConfig, EventConfig, PlatformConfig, SimulationParameters, TimeSimulationConfig,
)
from app.services.simulation_manager import SimulationManager, SimulationState, SimulationStatus  # noqa: E402

DEMO_ID = "sim_god_demo"

# name, entity type, stance, influence weight
PEOPLE = [
    ("Dean Whitford", "UniversityOfficial", "supportive", 3.0),
    ("Provost Okafor", "UniversityOfficial", "supportive", 2.5),
    ("Campus Herald", "MediaOutlet", "neutral", 2.8),
    ("City Evening Post", "MediaOutlet", "neutral", 2.2),
    ("Maya Chen", "Student", "opposing", 1.6),
    ("Luis Romero", "Student", "opposing", 1.2),
    ("Aisha Khan", "Student", "opposing", 1.4),
    ("Tom Becker", "Student", "neutral", 0.8),
    ("Prof. Elena Sato", "Professor", "opposing", 1.9),
    ("Prof. Mark Ruiz", "Professor", "supportive", 1.5),
    ("Student Union", "Organization", "opposing", 2.4),
    ("Alumni Board", "Organization", "supportive", 1.7),
    ("Nina Park", "Student", "observer", 0.5),
    ("Omar Haddad", "Student", "opposing", 1.0),
    ("Grace Liu", "Alumni", "neutral", 0.9),
    ("Finance Office", "UniversityOfficial", "supportive", 1.3),
]
TOPICS_IN_CONFIG = ["tuition hike", "library closure", "student union", "campus protest", "budget audit"]
SENTIMENT = {"supportive": 0.5, "opposing": -0.6, "neutral": 0.0, "observer": 0.0}


def make_demo(simulation_id: str = DEMO_ID, hours: int = 72) -> str:
    profiles, agent_configs = [], []
    for i, (name, kind, stance, influence) in enumerate(PEOPLE):
        profiles.append(OasisAgentProfile(
            user_id=i,
            user_name=name.lower().replace(" ", "_").replace(".", ""),
            name=name,
            bio=f"{kind} involved in the tuition debate. Stance: {stance}.",
            persona=(f"{name} is a {kind} at Riverside University. Stance: {stance}. "
                     "Speaks plainly about the tuition hike and the library closure."),
            age=20 + i, gender="other", country="US", profession=kind,
            interested_topics=["tuition hike", "library closure"],
            source_entity_uuid=f"ent-{i:04d}", source_entity_type=kind,
            follower_count=int(influence * 400), karma=int(influence * 900),
        ))
        agent_configs.append(AgentActivityConfig(
            agent_id=i, entity_uuid=f"ent-{i:04d}", entity_name=name, entity_type=kind,
            activity_level=min(1.0, 0.45 + influence / 6), active_hours=list(range(24)),
            stance=stance, sentiment_bias=SENTIMENT[stance], influence_weight=influence,
        ))

    sim_dir = os.path.join(Config.OASIS_SIMULATION_DATA_DIR, simulation_id)
    os.makedirs(sim_dir, exist_ok=True)
    writer = OasisProfileGenerator.__new__(OasisProfileGenerator)  # only its file writers are used
    writer.save_profiles(profiles, os.path.join(sim_dir, "twitter_profiles.csv"), platform="twitter")
    writer.save_profiles(profiles, os.path.join(sim_dir, "reddit_profiles.json"), platform="reddit")

    params = SimulationParameters(
        simulation_id=simulation_id, project_id="proj_god_demo", graph_id="graph_god_demo",
        simulation_requirement="How does campus opinion move after a tuition hike is announced?",
        time_config=TimeSimulationConfig(
            total_simulation_hours=hours, minutes_per_round=60,
            agents_per_hour_min=5, agents_per_hour_max=9,
            peak_hours=[], off_peak_hours=[], morning_hours=[], work_hours=[],
        ),
        agent_configs=agent_configs,
        event_config=EventConfig(
            initial_posts=[
                {"poster_agent_id": 0, "content": "Official notice: a tuition hike of 12% takes effect next term. "
                                                  "Weekend library closure is under review."},
                {"poster_agent_id": 10, "content": "The Student Union rejects the tuition hike. "
                                                   "Campus protest planned for Friday."},
            ],
            hot_topics=TOPICS_IN_CONFIG,
        ),
        twitter_config=PlatformConfig(platform="twitter"),
        reddit_config=PlatformConfig(platform="reddit"),
        llm_model="demo",
    )
    with open(os.path.join(sim_dir, "simulation_config.json"), "w", encoding="utf-8") as handle:
        handle.write(params.to_json())

    SimulationManager()._save_simulation_state(SimulationState(
        simulation_id=simulation_id, project_id="proj_god_demo", graph_id="graph_god_demo",
        status=SimulationStatus.READY, entities_count=len(PEOPLE), profiles_count=len(PEOPLE),
        entity_types=sorted({p[1] for p in PEOPLE}), profiles_generated=True, config_generated=True,
    ))
    return sim_dir


if __name__ == "__main__":
    print(make_demo())
