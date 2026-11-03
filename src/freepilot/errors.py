"""The base of every error freepilot reports to the user without a traceback."""


class FreepilotError(Exception):
    """A problem with the monitor, the config, or the command line request."""
