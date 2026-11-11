"""\n配置管理\n统一从项目根目录的 .env 文件加载配置\n"""

import os
from dotenv import load_dotenv

# 加载项目根目录的 .env 文件
# 路径: MiroFish/.env (相对于 backend/app/config.py)
project_root_env = os.path.join(os.path.dirname(__file__), '../../.env')

if os.path.exists(project_root_env):
    load_dotenv(project_root_env, override=True)
else:
    # 如果根目录没有 .env，尝试加载环境变量（用于生产环境）
    load_dotenv(override=True)


class Config:
    """Flask配置类"""
    
    # Flask配置
    SECRET_KEY = os.environ.get('SECRET_KEY', 'mirofish-secret-key')
    DEBUG = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    
    # JSON配置 - 禁用ASCII转义，让中文直接显示
    JSON_AS_ASCII = False
    
    # LLM provider: "anthropic" (Claude, through the Anthropic SDK) or
    # "openai" (any OpenAI-compatible API, the original MiroFish setup).
    LLM_PROVIDER = os.environ.get('LLM_PROVIDER', 'openai').strip().lower()

    # LLM配置（统一使用OpenAI格式）- used when LLM_PROVIDER=openai
    LLM_API_KEY = os.environ.get('LLM_API_KEY')
    LLM_BASE_URL = os.environ.get('LLM_BASE_URL', 'https://api.openai.com/v1')
    LLM_MODEL_NAME = os.environ.get('LLM_MODEL_NAME', 'gpt-4o-mini')

    # Claude - used when LLM_PROVIDER=anthropic. See app/utils/claude.py.
    ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY')
    CLAUDE_MODELS = {
        # ontology, report agent, graph search: executive-level synthesis
        'report': os.environ.get('CLAUDE_REPORT_MODEL', 'claude-sonnet-5-5'),
        # agent profiles and simulation config: many small structured calls
        'fast': os.environ.get('CLAUDE_FAST_MODEL', 'claude-haiku-5-5'),
        # every OASIS agent action and interview
        'simulation': os.environ.get('CLAUDE_SIMULATION_MODEL', 'claude-haiku-5-5'),
    }
    # Effort per tier (low / medium / high / xhigh / max; empty = model default).
    CLAUDE_EFFORT = {
        'report': os.environ.get('CLAUDE_REPORT_EFFORT', 'high'),
        'fast': os.environ.get('CLAUDE_FAST_EFFORT', 'low'),
        'simulation': os.environ.get('CLAUDE_SIMULATION_EFFORT', 'low'),
    }
    # Swarm agents act on a short context, so thinking is off by default to
    # keep runs cheap ("adaptive" turns it on). Thinking cannot be turned off
    # on the report model (Sonnet 5.5), only lowered with effort.
    CLAUDE_SIMULATION_THINKING = os.environ.get('CLAUDE_SIMULATION_THINKING', 'disabled')
    # Tokens of history an OASIS agent sees per call; the main cost lever of a run.
    CLAUDE_SIMULATION_CONTEXT_TOKENS = int(os.environ.get('CLAUDE_SIMULATION_CONTEXT_TOKENS', '24000'))

    # Cost control. A simulation stops early once the run (preparation +
    # simulation) reaches RUN_BUDGET_ZAR minus REPORT_RESERVE_ZAR, so the
    # report still fits in the budget. Set USD_ZAR_RATE to today's rate.
    RUN_BUDGET_ZAR = float(os.environ.get('RUN_BUDGET_ZAR', '50'))
    REPORT_RESERVE_ZAR = float(os.environ.get('REPORT_RESERVE_ZAR', '12'))
    USD_ZAR_RATE = float(os.environ.get('USD_ZAR_RATE', '18.5'))

    @classmethod
    def claude_model(cls, tier: str) -> str:
        return cls.CLAUDE_MODELS.get(tier) or cls.CLAUDE_MODELS['report']

    @classmethod
    def claude_effort(cls, tier: str) -> str:
        return (cls.CLAUDE_EFFORT.get(tier) or '').strip().lower()

    @classmethod
    def claude_thinking(cls, tier: str) -> str:
        return cls.CLAUDE_SIMULATION_THINKING.strip().lower() if tier == 'simulation' else 'adaptive'
    
    # Zep配置
    ZEP_API_KEY = os.environ.get('ZEP_API_KEY')
    
    # 文件上传配置
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50MB
    UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), '../uploads')
    ALLOWED_EXTENSIONS = {'pdf', 'md', 'txt', 'markdown'}
    
    # 文本处理配置
    DEFAULT_CHUNK_SIZE = 500  # 默认切块大小
    DEFAULT_CHUNK_OVERLAP = 50  # 默认重叠大小
    
    # OASIS模拟配置
    OASIS_DEFAULT_MAX_ROUNDS = int(os.environ.get('OASIS_DEFAULT_MAX_ROUNDS', '10'))
    OASIS_SIMULATION_DATA_DIR = os.path.join(os.path.dirname(__file__), '../uploads/simulations')
    
    # OASIS平台可用动作配置
    OASIS_TWITTER_ACTIONS = [
        'CREATE_POST', 'LIKE_POST', 'REPOST', 'FOLLOW', 'DO_NOTHING', 'QUOTE_POST'
    ]
    OASIS_REDDIT_ACTIONS = [
        'LIKE_POST', 'DISLIKE_POST', 'CREATE_POST', 'CREATE_COMMENT',
        'LIKE_COMMENT', 'DISLIKE_COMMENT', 'SEARCH_POSTS', 'SEARCH_USER',
        'TREND', 'REFRESH', 'DO_NOTHING', 'FOLLOW', 'MUTE'
    ]
    
    # Report Agent配置
    REPORT_AGENT_MAX_TOOL_CALLS = int(os.environ.get('REPORT_AGENT_MAX_TOOL_CALLS', '5'))
    REPORT_AGENT_MAX_REFLECTION_ROUNDS = int(os.environ.get('REPORT_AGENT_MAX_REFLECTION_ROUNDS', '2'))
    REPORT_AGENT_TEMPERATURE = float(os.environ.get('REPORT_AGENT_TEMPERATURE', '0.5'))
    
    @classmethod
    def validate(cls) -> list[str]:
        """验证必要配置"""
        errors: list[str] = []
        if cls.LLM_PROVIDER == "anthropic":
            if not cls.ANTHROPIC_API_KEY:
                errors.append("ANTHROPIC_API_KEY is not set (LLM_PROVIDER=anthropic)")
        elif cls.LLM_PROVIDER != "openai":
            errors.append(f"LLM_PROVIDER must be 'anthropic' or 'openai', not '{cls.LLM_PROVIDER}'")
        elif not cls.LLM_API_KEY:
            errors.append("LLM_API_KEY 未配置")
        if not cls.ZEP_API_KEY:
            errors.append("ZEP_API_KEY 未配置")
        if os.environ.get("ZEP_API_URL"):
            errors.append("ZEP_API_URL 不受支持；MiroFish 仅连接 Zep Cloud")
        if cls.DEBUG:
            import warnings
            warnings.warn("Flask DEBUG mode is enabled. Do not use in production.", RuntimeWarning)
        return errors
