"""
A ready-to-run simulation: the Gauteng tender market reacting to TenderFind
SA's R1,500 Bid Check. 16 agents, no Zep needed (no document upload).

    python scripts/god_demo/make_tenderfind.py [simulation_id]
"""
import os, sys
backend = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, backend)
from app.config import Config
from app.services.oasis_profile_generator import OasisAgentProfile, OasisProfileGenerator
from app.services.simulation_config_generator import (SimulationParameters, AgentActivityConfig,
    TimeSimulationConfig, EventConfig, PlatformConfig)
from app.services.simulation_manager import SimulationManager, SimulationState, SimulationStatus

SIM = sys.argv[1] if len(sys.argv) > 1 else "sim_tenderfind_live"
# name, type, stance on the Bid Check, influence, who they are
PEOPLE = [
 ("Jay Kgope (TenderFind SA)", "Founder", "supportive", 2.0, "Runs TenderFind SA in Pretoria. Launched the R1,500 24-hour AI Bid Check. Explains plainly, never promises wins, answers questions on WhatsApp."),
 ("Thabo Mokoena", "Civil contractor CIDB 2", "opposing", 1.6, "Owns a 9-person civil works company in Soshanguve. Has lost 4 municipal bids this year. Paid a consultant R8,000 who promised a win and delivered nothing. Deeply sceptical of paying anyone before a bid."),
 ("Lerato Dlamini", "Cleaning company owner", "neutral", 1.2, "Runs a cleaning company in Centurion with 22 staff. Bids for provincial cleaning tenders. Money is tight but she lost a big tender over an unsigned SBD form."),
 ("Sipho Nkosi", "Security company owner", "neutral", 1.1, "Owns a small security company in Midrand. Uses Facebook groups to find tenders. Worried about who sees his company documents."),
 ("Ayesha Patel", "IT supplier", "supportive", 1.3, "Runs a 4-person IT supply business in Pretoria East. Likes tools that save time; already pays for tender alerts."),
 ("Pieter van der Merwe", "General supplier", "opposing", 1.0, "Runs a general supplies business in Silverton. Thinks AI is hype and that bids are won through relationships, not paperwork."),
 ("Nomsa Khumalo", "Catering business owner", "neutral", 0.9, "New to tenders, owns a catering business in Mamelodi. Does not yet understand CSD or tax compliance PINs. Price sensitive."),
 ("Bongani Zulu", "Civil contractor CIDB 4", "supportive", 1.8, "Experienced contractor in Tembisa with a bid writer on staff. Open to a second check for big tenders, but expects real expertise."),
 ("Karabo Molefe", "Accountant", "neutral", 1.7, "Bookkeeper in Lyttelton who prepares tax and B-BBEE documents for 60 small businesses. Could refer clients if the service is trustworthy."),
 ("Mr. Mahlangu (municipal SCM official)", "Supply chain official", "observer", 2.2, "Supply chain management official at a Gauteng municipality. Sees the same disqualifying mistakes every week. Speaks carefully and never endorses vendors."),
 ("Gauteng SME Tender Forum", "Facebook group admin", "neutral", 2.4, "Admin of a large Facebook group where small businesses share tenders and ask for help. Bans spam and hard selling."),
 ("Naledi Sithole", "Business journalist", "observer", 1.9, "Writes about small business and township economy for a Gauteng news site. Asks critical questions about AI and consumer protection."),
 ("TenderFinder fan", "Competitor's customer", "opposing", 0.8, "Pays R79 a month for TenderFinder alerts and thinks R1,500 for a check is too much."),
 ("Zanele Mthembu", "Women-owned construction startup", "supportive", 1.0, "Started a women-owned construction company last year; registered on CSD with TenderFind's help. Trusts Jay."),
 ("Kabelo Ramaphosa", "Bid consultant", "opposing", 1.5, "Independent bid consultant who charges a percentage of contract value. Sees the AI Bid Check as cheap competition and doubts its quality."),
 ("Fatima Osman", "Print shop owner", "neutral", 0.7, "Runs a print and PostNet-style shop in Irene where contractors print bids. Hears every complaint about tenders at the counter."),
]
REQUIREMENT = ('How will small Gauteng businesses that bid for government tenders react to TenderFind SA launching a R1,500, 24-hour AI Bid Check? Which groups are interested, which are sceptical, what objections and trust concerns do they raise, how does price and the use of AI affect trust, and what message or proof would convert the sceptics?')
TOPICS = ["Bid Check", "R1,500", "disqualified", "tax compliance PIN", "AI", "trust"]
profiles, cfgs = [], []
for i, (name, kind, stance, inf, about) in enumerate(PEOPLE):
    profiles.append(OasisAgentProfile(user_id=i, user_name=f"user{i}_{name.split()[0].lower().strip('(').strip('.')}", name=name,
        bio=f"{kind}. {about[:120]}", persona=f"{name}: {about} Your view of TenderFind's Bid Check is {stance}. Write like a real South African small-business person on social media: short, direct, sometimes informal.",
        country="ZA", profession=kind, interested_topics=["government tenders", "small business"],
        source_entity_uuid=f"tf-{i:03d}", source_entity_type=kind, follower_count=int(inf * 300), karma=int(inf * 800)))
    cfgs.append(AgentActivityConfig(agent_id=i, entity_uuid=f"tf-{i:03d}", entity_name=name, entity_type=kind,
        activity_level=min(1.0, 0.5 + inf / 6), active_hours=list(range(24)), stance=stance,
        sentiment_bias={"supportive": 0.4, "opposing": -0.5, "neutral": 0.0, "observer": 0.0}[stance], influence_weight=inf))
d = os.path.join(Config.OASIS_SIMULATION_DATA_DIR, SIM); os.makedirs(d, exist_ok=True)
w = OasisProfileGenerator.__new__(OasisProfileGenerator)
w.save_profiles(profiles, os.path.join(d, "twitter_profiles.csv"), platform="twitter")
w.save_profiles(profiles, os.path.join(d, "reddit_profiles.json"), platform="reddit")
params = SimulationParameters(simulation_id=SIM, project_id="proj_tenderfind", graph_id="none",
    simulation_requirement=REQUIREMENT,
    time_config=TimeSimulationConfig(total_simulation_hours=24, minutes_per_round=60, agents_per_hour_min=4, agents_per_hour_max=7,
        peak_hours=[], off_peak_hours=[], morning_hours=[], work_hours=[]),
    agent_configs=cfgs,
    event_config=EventConfig(initial_posts=[
        {"poster_agent_id": 0, "content": "New from TenderFind SA: the 24-hour Bid Check. Send your RFQ or tender before you submit, and within 24 hours you get a report on missing documents (unsigned SBD forms, CSD number, tax PIN, CIDB grade), weak sections and suggested rewrites. R1,500 for an RFQ. Checked with AI, with your written consent; personal details removed first. We never promise a win. Message us on WhatsApp."},
        {"poster_agent_id": 10, "content": "Members keep losing bids on paperwork. Has anyone tried a pre-submission bid check service? Share honest experiences, no spam please."}],
        hot_topics=TOPICS),
    twitter_config=PlatformConfig(platform="twitter"), reddit_config=PlatformConfig(platform="reddit"), llm_model=Config.LLM_MODEL_NAME)
open(os.path.join(d, "simulation_config.json"), "w").write(params.to_json())
SimulationManager()._save_simulation_state(SimulationState(simulation_id=SIM, project_id="proj_tenderfind", graph_id="none",
    status=SimulationStatus.READY, entities_count=len(PEOPLE), profiles_count=len(PEOPLE),
    entity_types=sorted({p[1] for p in PEOPLE}), profiles_generated=True, config_generated=True))
print(SIM, "ready with", len(PEOPLE), "agents")
