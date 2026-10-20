"""RepoPilot: private, history-aware code review on open models you run yourself."""

import warnings

__version__ = "2.0.0"

# RepoPilot parses the user's source with `ast`; old code (e.g. "\*" in Python 2-era strings) makes the
# compiler print a SyntaxWarning per file, which is noise about their code, not a RepoPilot problem.
warnings.filterwarnings("ignore", category=SyntaxWarning)
