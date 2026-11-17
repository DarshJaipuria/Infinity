SKILLS = {}


class Skill:
    def __init__(self, name, description, playbook, tools, direct_output=False,
                 finalize=None, max_steps=None, cleanup=None):
        self.name = name
        self.description = description
        self.playbook = playbook            # instructions for the mini-loop
        self.tools = tools                  # sub-tool names this skill may use
        self.direct_output = direct_output  # True = show result to user as-is
        self.finalize = finalize            # optional function(summary) -> final text
        self.max_steps = max_steps          # optional step limit (default: config.MAX_SKILL_STEPS)
        self.cleanup = cleanup              # optional function, always runs when the skill ends


def register(skill):
    SKILLS[skill.name] = skill


def get_schemas():
    """Main tools as the router model sees them."""
    return [
        {
            "type": "function",
            "function": {
                "name": s.name,
                "description": s.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "request": {
                            "type": "string",
                            "description": "The user's full request",
                        }
                    },
                    "required": ["request"],
                },
            },
        }
        for s in SKILLS.values()
    ]


from . import write_code, file_manager, gmail_compose, web_research  # noqa: E402,F401