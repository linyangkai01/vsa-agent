"""Tool registration module.

Imports all tool modules to trigger @register_tool decorators.
Mirrors NVIDIA tools/register.py pattern.
"""

# Core tools
import vsa_agent.tools.echo_tool  # noqa: F401
import vsa_agent.tools.find_video_tool  # noqa: F401
import vsa_agent.tools.frame_extract  # noqa: F401
import vsa_agent.tools.prompt_gen  # noqa: F401
import vsa_agent.tools.video_understanding  # noqa: F401

# Search tools
import vsa_agent.tools.search  # noqa: F401
import vsa_agent.tools.embed_search  # noqa: F401
import vsa_agent.tools.attribute_search  # noqa: F401
import vsa_agent.tools.query_builders  # noqa: F401

# Agents (registered as tools)
import vsa_agent.agents.search_agent  # noqa: F401
import vsa_agent.agents.critic_agent  # noqa: F401
